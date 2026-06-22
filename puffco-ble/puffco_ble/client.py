"""High-level Puffco client with connect, reconnect, and data polling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from dataclasses import replace
from typing import Awaitable, Callable, Literal

from bleak import BleakError
from bleak.backends.device import BLEDevice

from puffco_ble.ble_client import PuffcoBleakClient
from puffco_ble.constants import (
    BLE_DISCOVERY_SERVICES,
    Characteristics,
    LoraxCharacteristics,
)
from puffco_ble.encoding import (
    battery_charge_state_name,
    is_battery_charging,
    operating_state_name,
)
from puffco_ble.models import PuffcoData
from puffco_ble.protocol import find_device_by_address

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_TIMEOUT = 15.0
DEFAULT_CONNECT_TIMEOUT = 60.0
DEFAULT_RECONNECT_DELAY = 3.0
MAX_CONNECT_RETRIES = 5

# Prefer filtered Lorax discovery first (fewer WinRT "services changed" drops).
# NOTE: do NOT auto-unpair here. An existing OS bond is reused successfully on
# reconnect; tearing it down mid-retry leaves the Windows stack "Unreachable".
# Use the manual `puffco-cli unpair` command only when the bond is truly stale.
_CONNECT_STRATEGIES: tuple[dict, ...] = (
    {"pair": False, "services": BLE_DISCOVERY_SERVICES, "winrt": {}},
    {"pair": False, "services": None, "winrt": {}},
    {"pair": False, "services": BLE_DISCOVERY_SERVICES, "winrt": {}},
    {"pair": False, "services": None, "winrt": {}},
)


class PuffcoClient:
    """Async context manager wrapping Puffco BLE connect/auth/read/write."""

    def __init__(
        self,
        address: str,
        *,
        ble_device: BLEDevice | None = None,
        connector: Callable[
            [BLEDevice, Callable[[PuffcoBleakClient], None]],
            Awaitable[PuffcoBleakClient],
        ]
        | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        scan_timeout: float = DEFAULT_SCAN_TIMEOUT,
    ) -> None:
        self.address = address.upper()
        self.connect_timeout = connect_timeout
        self.reconnect_delay = reconnect_delay
        self.scan_timeout = scan_timeout
        self._client: PuffcoBleakClient | None = None
        self._lock = asyncio.Lock()
        self._protocol: Literal["flat", "lorax"] = "flat"
        self._connected_once = False
        # Tracks whether we hold a working bonded link this session, so we only
        # pair() once (in pairing mode) and reconnect silently afterwards.
        self._bonded = False
        self._last_lantern_brightness: int | None = None
        # When running inside Home Assistant the BLEDevice is sourced from HA's
        # Bluetooth manager (we must NOT run our own scanner) and the connection
        # is established via an injected connector (bleak-retry-connector).
        self._ble_device = ble_device
        self._connector = connector
        self._is_windows = sys.platform == "win32"
        self._on_disconnect_callback: Callable[[], None] | None = None

    def set_ble_device(self, device: BLEDevice) -> None:
        """Refresh the BLEDevice (HA hands us a fresh one each connect)."""
        self._ble_device = device

    def set_on_disconnect(self, callback: Callable[[], None] | None) -> None:
        """Optional callback when the OS/BLE stack drops the GATT link."""
        self._on_disconnect_callback = callback

    def reset_bond_state(self) -> None:
        """Clear session bond flag so the next connect may pair() again."""
        self._bonded = False

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def protocol(self) -> Literal["flat", "lorax"]:
        return self._protocol

    @property
    def bleak(self) -> PuffcoBleakClient:
        if self._client is None:
            raise RuntimeError("Not connected")
        return self._client

    async def __aenter__(self) -> PuffcoClient:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.disconnect()

    def _connect_kwargs(self) -> dict:
        return {}

    def _on_disconnect(self, _client: PuffcoBleakClient) -> None:
        if self._connected_once:
            _LOGGER.warning("Disconnected from %s", self.address)
        if self._on_disconnect_callback is not None:
            self._on_disconnect_callback()

    async def connect(self) -> None:
        if self.is_connected:
            return
        # Drop any stale GATT object before opening a new session (important
        # for ESPHome proxy after the Peak sleeps or power-cycles).
        if self._client is not None:
            with contextlib.suppress(Exception):
                if self._client.is_connected:
                    await self._client.disconnect()
            self._client = None

        # Home Assistant mode: device + connector are injected; never scan.
        if self._connector is not None or self._ble_device is not None:
            await self._connect_via_ha()
            return

        last_err: Exception | None = None
        strategy_index = 0
        for attempt in range(1, MAX_CONNECT_RETRIES + 1):
            try:
                strategy = _CONNECT_STRATEGIES[
                    strategy_index % len(_CONNECT_STRATEGIES)
                ]
                await self._connect_once(
                    pair=strategy.get("pair", False),
                    services=strategy.get("services"),
                    winrt=strategy.get("winrt"),
                    reset_bond=strategy.get("reset_bond", False),
                )
                return
            except (BleakError, OSError, TimeoutError) as err:
                last_err = err
                await self.disconnect()
                strategy_index += 1
                if attempt < MAX_CONNECT_RETRIES:
                    _LOGGER.warning(
                        "Connect attempt %s/%s failed (%s), retrying in %ss...",
                        attempt,
                        MAX_CONNECT_RETRIES,
                        err,
                        self.reconnect_delay,
                    )
                    await asyncio.sleep(self.reconnect_delay)

        assert last_err is not None
        raise last_err

    async def _connect_once(
        self,
        *,
        pair: bool = False,
        services: list[str] | None = BLE_DISCOVERY_SERVICES,
        winrt: dict | None = None,
        reset_bond: bool = False,
    ) -> None:
        _LOGGER.info(
            "Scanning for %s up to %.0fs (Peak must be in pairing mode: blue light bar)...",
            self.address,
            self.scan_timeout,
        )
        device = await find_device_by_address(
            self.address, timeout=self.scan_timeout
        )
        if device is None:
            raise BleakError(
                f"Device {self.address} not visible during scan. "
                "Put the Peak in pairing mode (hold power until blue bar), "
                "close the phone app, and if Windows already paired it remove "
                "it from Settings → Bluetooth first."
            )

        label = device.name or self.address
        _LOGGER.info(
            "Found %r, connecting (pair=%s, filtered_services=%s, winrt=%s)...",
            label,
            pair,
            services is not None,
            winrt or {},
        )
        self._connected_once = False
        client_kwargs: dict = {
            "disconnected_callback": self._on_disconnect,
            "timeout": self.connect_timeout,
        }
        if self._is_windows:
            # Puffco rejects Windows pre-connect pairing; winrt opts tune the
            # WinRT backend. These kwargs are Windows-only.
            client_kwargs["pair"] = False
            client_kwargs["winrt"] = winrt or {}
        if services is not None:
            client_kwargs["services"] = services
        self._client = PuffcoBleakClient(device, **client_kwargs)

        if reset_bond:
            await self._reset_os_bond(self._client)

        await self._client.connect(timeout=self.connect_timeout)
        if not self._client.is_connected:
            raise BleakError(
                f"GATT session did not stay connected to {self.address}"
            )

        self._connected_once = True
        await self._finalize_connection()

    async def _connect_via_ha(self) -> None:
        """Connect using a HA-sourced BLEDevice (no scanning, BlueZ-friendly)."""
        device = self._ble_device
        if device is None:
            raise BleakError(
                "PuffcoClient HA mode requires a BLEDevice (call set_ble_device)"
            )
        _LOGGER.info("Connecting to %s via HA Bluetooth...", self.address)
        self._connected_once = False
        if self._connector is not None:
            self._client = await self._connector(device, self._on_disconnect)
        else:
            self._client = PuffcoBleakClient(
                device,
                disconnected_callback=self._on_disconnect,
                timeout=self.connect_timeout,
            )
            await self._client.connect(timeout=self.connect_timeout)
        if not self._client.is_connected:
            raise BleakError(
                f"GATT session did not stay connected to {self.address}"
            )
        self._connected_once = True
        try:
            await self._finalize_connection()
        except Exception as first_err:
            # Reuse an existing OS/proxy bond first (normal after HA restart or
            # wake from sleep). Only call pair() if the Lorax handshake fails.
            _LOGGER.debug(
                "Handshake failed for %s without bond step (%s); trying pair()",
                self.address,
                first_err,
            )
            await self._bond_if_needed(force=True)
            await self._finalize_connection()
        self._bonded = True

    async def _bond_if_needed(self, *, force: bool = False) -> None:
        """Establish an OS-level bond (BlueZ/ESP32) before touching Lorax chars.

        Only used when the Lorax handshake fails without it — e.g. first pairing
        or a lost bond. Skipped on reconnect when the OS bond is still valid.

        No-op on the WinRT backend (Puffco rejects Windows pairing); never fatal.
        """
        if self._is_windows or self._client is None:
            return
        if self._bonded and not force:
            return
        try:
            paired = await self._client.pair()
            _LOGGER.info(
                "Bond step for %s: %s",
                self.address,
                "bonded" if paired else "already bonded / not required",
            )
        except NotImplementedError:
            _LOGGER.debug("Bonding not implemented by backend; relying on auto-bond")
        except Exception as err:  # noqa: BLE001 - best-effort, never fatal
            # Backends differ (BlueZ, ESPHome proxy); a pairing hiccup must not
            # abort an otherwise-good connection. BlueZ/ESP32 may auto-bond on
            # first encrypted access anyway.
            _LOGGER.debug("Bond step for %s failed (continuing): %s", self.address, err)

    async def _finalize_connection(self) -> None:
        """Detect protocol, init Lorax, and read identity (shared by both paths)."""
        assert self._client is not None
        lorax_service = self._client.services.get_service(
            LoraxCharacteristics.LORAX_SERVICE_UUID
        )
        if lorax_service:
            self._protocol = "lorax"
            if not await self._client.init_lorax_protocol():
                raise BleakError("Lorax protocol initialization failed")
        else:
            # The Peak Pro (FW AW) is always a Lorax device. A missing Lorax
            # service means an incomplete GATT DB — typically the link dropped
            # mid-discovery. Standard services like Device Info (0x2A28) can
            # still be present, so we must NOT fall back to the flat protocol
            # here (that read would fail). Retry with fresh discovery.
            raise BleakError(
                "Lorax service missing from GATT discovery (incomplete/dropped); "
                "retrying"
            )

        self._client.firmware_revision = await self._client.get_firmware_revision()
        self._client.device_name = await self._client.get_device_name()
        _LOGGER.info(
            "Connected to %s (%s, firmware %s, protocol %s)",
            self._client.device_name,
            self.address,
            self._client.firmware_revision,
            self._protocol,
        )

    @staticmethod
    async def _reset_os_bond(client: PuffcoBleakClient) -> bool:
        """Remove a stale OS pairing so the Peak can bond fresh.

        On Windows a leftover bond makes the OS reuse old encryption keys; the
        Peak (in pairing mode) rejects them and the link never establishes.
        Dropping the bond first forces a clean re-pair on the next connect.
        """
        try:
            removed = await client.unpair()
            _LOGGER.info(
                "Reset OS bond before connect: %s",
                "removed stale pairing" if removed else "no existing pairing",
            )
            return bool(removed)
        except (BleakError, OSError, NotImplementedError) as err:
            _LOGGER.debug("Bond reset skipped/unsupported: %s", err)
            return False

    async def unpair(self) -> bool:
        """Remove the OS-level bond for this device.

        On WinRT the pairing record can only be resolved from a discovered
        device, so scan first (Peak must be advertising / in pairing mode).
        """
        device = await find_device_by_address(self.address, timeout=self.scan_timeout)
        if device is None:
            _LOGGER.warning(
                "Cannot unpair %s: device not found in scan. Put the Peak in "
                "pairing mode (blue bar) and keep it close.",
                self.address,
            )
            client = PuffcoBleakClient(self.address)
        else:
            client = PuffcoBleakClient(device)
        return await self._reset_os_bond(client)

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._connected_once = False

    async def ensure_connected(self) -> None:
        if not self.is_connected:
            await self.connect()

    async def _read_battery_charge(
        self, client: PuffcoBleakClient
    ) -> tuple[bool, str, float | None]:
        state_id = await client.get_battery_charge_state()
        charging = is_battery_charging(state_id)
        eta = (
            await client.get_battery_charge_eta_seconds(state_id)
            if charging
            else None
        )
        return charging, battery_charge_state_name(state_id), eta

    async def fetch_data(self) -> PuffcoData:
        async with self._lock:
            await self.ensure_connected()
            client = self.bleak
            profile = await client.get_profile()
            profile_temps = []
            profile_times = []
            for idx in range(4):
                profile_temps.append(await client.get_profile_temp(idx))
                profile_times.append(await client.get_profile_time(idx))
            profile_temp = profile_temps[profile] if profile < len(profile_temps) else 0.0
            heater_temp = await client.get_heater_temp_c()
            state_id = await client.get_operating_state()
            lantern_on = bool(client.lantern_enabled)
            if client.lantern_enabled is None and not client.use_lorax_protocol:
                try:
                    status = await client.read_gatt_char(Characteristics.LANTERN_STATUS)
                    lantern_on = bool(status[0]) if status else False
                    client.lantern_enabled = lantern_on
                except BleakError:
                    lantern_on = False

            charging, charge_state, charge_eta = await self._read_battery_charge(
                client
            )

            from puffco_ble.constants import is_heat_cycle_state_id

            state_elapsed_s: float | None = None
            state_total_s: float | None = None
            if is_heat_cycle_state_id(state_id):
                state_elapsed_s = await client.get_state_elapsed_time()
                state_total_s = await client.get_state_total_time()

            return PuffcoData(
                total_dabs=await client.get_total_dab_count(),
                trip_dabs=await client.get_trip_dab_count(),
                dabs_per_day=await client.get_daily_dab_count(),
                heater_temp_c=heater_temp,
                profile_temp_c=profile_temp,
                profile_temps_c=profile_temps,
                profile_times_s=profile_times,
                active_profile=profile,
                operating_state=operating_state_name(state_id),
                state_elapsed_s=state_elapsed_s,
                state_total_s=state_total_s,
                battery_percent=await client.get_battery_percentage(),
                lantern_on=lantern_on,
                firmware=client.firmware_revision,
                protocol=self._protocol,
                device_name=client.device_name,
                model_name=await client.get_device_model(return_name=True),
                stealth_mode=await client.get_stealth_mode(),
                battery_charging=charging,
                battery_charge_state=charge_state,
                charge_eta_seconds=charge_eta,
            )

    async def fetch_data_fast(
        self,
        base: PuffcoData | None = None,
        *,
        profile_index: int | None = None,
    ) -> PuffcoData:
        """Read only fast-changing fields (for post-command refresh)."""
        if base is None:
            return await self.fetch_data()

        async with self._lock:
            await self.ensure_connected()
            client = self.bleak
            profile = await client.get_profile()
            profile_temps = list(base.profile_temps_c)
            profile_times = list(base.profile_times_s)
            if profile_index is not None:
                profile_temps[profile_index] = await client.get_profile_temp(
                    profile_index
                )
                profile_times[profile_index] = await client.get_profile_time(
                    profile_index
                )
            lantern_on = (
                bool(client.lantern_enabled)
                if client.lantern_enabled is not None
                else base.lantern_on
            )
            charging, charge_state, charge_eta = await self._read_battery_charge(
                client
            )
            state_id = await client.get_operating_state()
            from puffco_ble.constants import is_heat_cycle_state_id

            state_elapsed_s = base.state_elapsed_s
            state_total_s = base.state_total_s
            if is_heat_cycle_state_id(state_id):
                state_elapsed_s = await client.get_state_elapsed_time()
                state_total_s = await client.get_state_total_time()
            else:
                state_elapsed_s = None
                state_total_s = None

            return replace(
                base,
                heater_temp_c=await client.get_heater_temp_c(),
                profile_temps_c=profile_temps,
                profile_times_s=profile_times,
                profile_temp_c=(
                    profile_temps[profile]
                    if profile < len(profile_temps)
                    else base.profile_temp_c
                ),
                active_profile=profile,
                operating_state=operating_state_name(state_id),
                state_elapsed_s=state_elapsed_s,
                state_total_s=state_total_s,
                battery_percent=await client.get_battery_percentage(),
                lantern_on=lantern_on,
                stealth_mode=await client.get_stealth_mode(),
                battery_charging=charging,
                battery_charge_state=charge_state,
                charge_eta_seconds=charge_eta,
            )

    async def set_profile_temperature(self, profile: int, celsius: float) -> None:
        async with self._lock:
            await self.ensure_connected()
            await self.bleak.set_profile_temp(celsius, profile)

    async def set_profile_time(self, profile: int, seconds: float) -> None:
        async with self._lock:
            await self.ensure_connected()
            await self.bleak.set_profile_time(seconds, profile)

    async def start_session(self) -> None:
        async with self._lock:
            await self.ensure_connected()
            await self.bleak.start_heat_cycle()

    async def abort_session(self) -> None:
        async with self._lock:
            await self.ensure_connected()
            await self.bleak.abort_heat_cycle()

    async def set_lantern_color_rgb(self, r: int, g: int, b: int) -> None:
        async with self._lock:
            await self.ensure_connected()
            await self.bleak.send_lantern_color(r, g, b)

    async def set_lantern(
        self,
        *,
        r: int,
        g: int,
        b: int,
        effect_name: str,
        brightness: int | None = None,
        enabled: bool = True,
    ) -> None:
        """Apply lantern color, effect, brightness, and on/off."""
        from puffco_ble.constants import LANTERN_TIME_SEC
        from puffco_ble.encoding import pack_static_lantern_color
        from puffco_ble.lantern_effects import (
            DEFAULT_LANTERN_EFFECT,
            LANTERN_EFFECT_BY_NAME,
        )

        effect = LANTERN_EFFECT_BY_NAME.get(effect_name)
        if effect is None:
            effect = LANTERN_EFFECT_BY_NAME[DEFAULT_LANTERN_EFFECT]

        async with self._lock:
            await self.ensure_connected()
            bleak = self.bleak
            already_on = bool(bleak.lantern_enabled)

            if brightness is not None and brightness != self._last_lantern_brightness:
                await bleak.send_lantern_brightness(brightness)
                self._last_lantern_brightness = brightness

            if effect.kind == "preset" and effect.preset is not None:
                preset = bytearray(effect.preset)
                if bleak.lantern_color != preset:
                    await bleak.send_lantern_color_bytes(preset)
            else:
                mode = effect.mode if effect.mode is not None else 1
                payload = bytearray(pack_static_lantern_color(r, g, b, mode=int(mode)))
                if bleak.lantern_color != payload:
                    await bleak.send_lantern_color(r, g, b, mode=int(mode))

            if enabled:
                if not already_on:
                    await bleak.send_lantern_time(LANTERN_TIME_SEC)
                await bleak.send_lantern_status(True)
            else:
                await bleak.send_lantern_status(False)

    async def set_lantern_enabled(self, enabled: bool) -> None:
        async with self._lock:
            await self.ensure_connected()
            await self.bleak.send_lantern_status(enabled)

    async def auth_test(self) -> bool:
        """Verify authenticated read access to a protected characteristic."""
        async with self._lock:
            await self.ensure_connected()
            try:
                temp = await self.bleak.get_heater_temp_c()
                _LOGGER.info("Auth test OK (heater temp=%s)", temp)
                return True
            except BleakError as err:
                _LOGGER.error("Auth test failed: %s", err)
                return False
