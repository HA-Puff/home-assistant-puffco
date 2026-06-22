"""Active Bluetooth data update coordinator for Puffco."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta

from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo as EntityDeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_BLOCK_START_WHILE_CHARGING,
    CONF_FAST_POLL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_CHARGING_STARTED,
    EVENT_DISCONNECTED,
    EVENT_SESSION_FINISHED,
    EVENT_SESSION_STARTED,
    FULL_POLL_EVERY,
    HEAT_POLL_INTERVAL,
    POLL_INTERVAL,
    RECONNECT_INTERVAL,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_WAKE_DELAY,
    is_heat_cycle_state,
)
from puffco_ble.ble_client import PuffcoBleakClient
from puffco_ble.client import PuffcoClient
from puffco_ble.encoding import operating_state_name
from puffco_ble.models import PuffcoData

_LOGGER = logging.getLogger(__name__)

DEVICE_STARTUP_TIMEOUT = 30
VALIDATE_TIMEOUT = 45


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


def _make_connector(
    hass: HomeAssistant,
    mac: str,
) -> Callable[
    [BLEDevice, Callable[[PuffcoBleakClient], None]], Awaitable[PuffcoBleakClient]
]:
    """Build a connector that uses HA's bleak-retry-connector."""

    @callback
    def _ble_device_callback() -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(hass, mac, connectable=True)

    async def _connect(device: BLEDevice, on_disconnect) -> PuffcoBleakClient:
        return await establish_connection(
            PuffcoBleakClient,
            device,
            device.name or mac,
            disconnected_callback=on_disconnect,
            ble_device_callback=_ble_device_callback,
        )

    return _connect


def _build_client(hass: HomeAssistant, mac: str) -> PuffcoClient:
    client = PuffcoClient(mac, connector=_make_connector(hass, mac))
    device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
    if device is not None:
        client.set_ble_device(device)
    return client


async def validate_connection(hass: HomeAssistant, mac: str) -> dict[str, str]:
    """Verify BLE connect + auth during config flow."""
    device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
    if device is None:
        _LOGGER.warning(
            "Validate: %s is not visible to a connectable HA Bluetooth adapter",
            mac,
        )
        raise CannotConnect(f"Puffco {mac} not visible to Home Assistant Bluetooth")
    client = _build_client(hass, mac)
    _LOGGER.debug("Validate: starting connect to %s (device=%s)", mac, device)
    try:
        async with asyncio.timeout(VALIDATE_TIMEOUT):
            await client.connect()
            if not await client.auth_test():
                raise CannotConnect("Authentication failed")
            data = await client.fetch_data()
        _LOGGER.info(
            "Validate: success for %s (name=%s, fw=%s, model=%s)",
            mac,
            data.device_name,
            data.firmware,
            data.model_name,
        )
        return {
            "device_name": data.device_name,
            "firmware": data.firmware,
            "model": data.model_name,
        }
    except CannotConnect:
        raise
    except TimeoutError as err:
        raise CannotConnect(f"Timed out talking to {mac}") from err
    except Exception as err:
        _LOGGER.exception("Validate: unexpected error talking to %s", mac)
        raise CannotConnect(str(err)) from err
    finally:
        await client.disconnect()


class PuffcoDataUpdateCoordinator(ActiveBluetoothDataUpdateCoordinator[PuffcoData]):
    """Poll the Puffco over BLE with automatic wake reconnect."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        self.mac = entry.data[CONF_MAC]
        self._client = _build_client(hass, self.mac)
        self._client.set_on_disconnect(self._on_client_disconnect)
        self._lock = asyncio.Lock()
        self._ready_event = asyncio.Event()
        self._needs_reconnect = True
        self._ble_connected = False
        self._advertising = False
        self._write_in_progress = False
        self._interval_poll_count = 0
        self._last_interval_poll: datetime | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._pending_ble_device: BLEDevice | None = None
        self._session_listeners: list[Callable[[str, dict], None]] = []
        self._previous_charging: bool | None = None
        self.device_info = EntityDeviceInfo(
            identifiers={(DOMAIN, self.mac)},
            name=entry.title,
            manufacturer="Puffco",
            model="Peak Pro",
            connections={(CONNECTION_BLUETOOTH, self.mac)},
        )
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=self.mac,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_poll_device,
            mode=BluetoothScanningMode.ACTIVE,
            connectable=True,
        )

    @property
    def ble_connected(self) -> bool:
        """True when a live authenticated BLE session is up."""
        return self._ble_connected and self._client.is_connected

    @property
    def is_advertising(self) -> bool:
        """True when the Peak is broadcasting (stops once we connect)."""
        return self._advertising

    @property
    def block_start_while_charging(self) -> bool:
        return self.config_entry.options.get(
            CONF_BLOCK_START_WHILE_CHARGING, True
        )

    @callback
    def async_register_session_listener(
        self, listener: Callable[[str, dict], None]
    ) -> Callable[[], None]:
        """Register for session started/finished callbacks."""

        self._session_listeners.append(listener)

        @callback
        def _remove() -> None:
            with contextlib.suppress(ValueError):
                self._session_listeners.remove(listener)

        return _remove

    def _update_device_registry(self, data: PuffcoData) -> None:
        """Refresh device metadata after the first successful poll."""
        model = data.model_name or "Peak Pro"
        self.device_info = EntityDeviceInfo(
            identifiers={(DOMAIN, self.mac)},
            name=self.config_entry.title,
            manufacturer="Puffco",
            model=model,
            sw_version=data.firmware or None,
            connections={(CONNECTION_BLUETOOTH, self.mac)},
        )
        dev_reg = dr.async_get(self.hass)
        if device := dev_reg.async_get_device({(DOMAIN, self.mac)}):
            dev_reg.async_update_device(
                device.id,
                model=model,
                sw_version=data.firmware or device.sw_version,
                connections={(CONNECTION_BLUETOOTH, self.mac)},
            )

    @callback
    def _dispatch_session_event(self, event_type: str, data: dict) -> None:
        for listener in self._session_listeners:
            listener(event_type, data)

    def _logbook(self, message: str, name: str | None = None) -> None:
        from homeassistant.components import logbook

        logbook.async_log_entry(
            self.hass,
            message,
            name=name or self.config_entry.title,
            domain=DOMAIN,
        )

    @callback
    def _on_data_updated(
        self, previous: PuffcoData | None, current: PuffcoData
    ) -> None:
        """Detect session and connectivity transitions."""
        self._update_device_registry(current)
        prev_state = previous.operating_state if previous else None
        new_state = current.operating_state
        if prev_state != new_state:
            self._on_operating_state_change(previous, current, prev_state, new_state)

        prev_charging = (
            previous.battery_charging if previous else self._previous_charging
        )
        if prev_charging is False and current.battery_charging:
            payload = self._event_payload(current)
            self.hass.bus.async_fire(EVENT_CHARGING_STARTED, payload)
            self._logbook("Started charging")
        self._previous_charging = current.battery_charging

    @callback
    def _on_operating_state_change(
        self,
        previous: PuffcoData | None,
        current: PuffcoData,
        prev_state: str | None,
        new_state: str,
    ) -> None:
        was_heat = is_heat_cycle_state(prev_state)
        now_heat = is_heat_cycle_state(new_state)
        payload = self._event_payload(current)

        if not was_heat and now_heat:
            event_data = {
                **payload,
                "profile": current.active_profile + 1,
                "target_temperature": current.profile_temp_c,
                "operating_state": new_state,
            }
            self.hass.bus.async_fire(EVENT_SESSION_STARTED, event_data)
            self._dispatch_session_event("started", event_data)
            self._logbook(
                f"Heat session started (profile {current.active_profile + 1}, "
                f"{round(current.profile_temp_c)}°C)"
            )
        elif was_heat and not now_heat:
            event_data = {
                **payload,
                "profile": current.active_profile + 1,
                "previous_state": prev_state,
                "operating_state": new_state,
            }
            self.hass.bus.async_fire(EVENT_SESSION_FINISHED, event_data)
            self._dispatch_session_event("finished", event_data)
            self._logbook("Heat session finished")

    def _event_payload(self, data: PuffcoData) -> dict:
        device = dr.async_get(self.hass).async_get_device({(DOMAIN, self.mac)})
        return {
            "device_id": device.id if device else None,
            "mac": self.mac,
            "battery_percent": data.battery_percent,
        }

    def _create_reconnect_issue(self, error: str) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"reconnect_{self.mac}",
            data={"mac": self.mac},
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="reconnect_failed",
            translation_placeholders={"name": self.config_entry.title, "error": error},
        )

    def _clear_reconnect_issue(self) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, f"reconnect_{self.mac}")

    @callback
    def _on_client_disconnect(self) -> None:
        """BLE link dropped (sleep, range, idle timeout)."""
        self._ble_connected = False
        self._needs_reconnect = True
        device = dr.async_get(self.hass).async_get_device({(DOMAIN, self.mac)})
        self.hass.bus.async_fire(
            EVENT_DISCONNECTED,
            {"device_id": device.id if device else None, "mac": self.mac},
        )
        self._logbook("Bluetooth disconnected")
        self.async_update_listeners()
        self._schedule_reconnect()

    @callback
    def _schedule_reconnect(self, device: BLEDevice | None = None) -> None:
        """Queue a reconnect attempt (waits for lock; never skipped)."""
        if device is not None:
            self._pending_ble_device = device
        if self.hass.is_stopping:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_task(self._async_reconnect_worker())

    async def _async_reconnect_worker(self) -> None:
        """Retry GATT connect while the Peak is advertising."""
        if self._ble_connected and self._client.is_connected:
            return
        self._needs_reconnect = True

        if self._pending_ble_device is not None:
            await asyncio.sleep(RECONNECT_WAKE_DELAY)

        last_err: Exception | None = None
        for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
            device = self._pending_ble_device
            if device is None:
                device = bluetooth.async_ble_device_from_address(
                    self.hass, self.mac, connectable=True
                )
            if device is None:
                _LOGGER.debug(
                    "%s reconnect attempt %s: not visible yet",
                    self.mac,
                    attempt,
                )
                return
            previous_data = self.data
            try:
                self.data = await self._async_fetch_data(device)
            except Exception as err:
                last_err = err
                _LOGGER.warning(
                    "Reconnect attempt %s/%s for %s failed: %s",
                    attempt,
                    RECONNECT_MAX_ATTEMPTS,
                    self.mac,
                    err,
                )
                self._needs_reconnect = True
                self._ble_connected = False
                async with self._lock:
                    await self._client.disconnect()
                if attempt < RECONNECT_MAX_ATTEMPTS:
                    await asyncio.sleep(min(2 * attempt, 6))
                continue
            self._pending_ble_device = None
            _LOGGER.info("Reconnected to %s", self.mac)
            self._clear_reconnect_issue()
            self._on_data_updated(previous_data, self.data)
            self.async_update_listeners()
            return

        if last_err is not None:
            _LOGGER.warning(
                "%s reconnect gave up after %s attempts: %s",
                self.mac,
                RECONNECT_MAX_ATTEMPTS,
                last_err,
            )
            self._create_reconnect_issue(str(last_err))

    @callback
    def _mark_online(self) -> None:
        self._ble_connected = True
        self._needs_reconnect = False
        self._available = True

    @callback
    def _async_start(self) -> None:
        super()._async_start()
        self._on_stop.append(
            async_track_time_interval(
                self.hass,
                self._async_interval_poll,
                timedelta(seconds=HEAT_POLL_INTERVAL),
            )
        )
        self._on_stop.append(
            async_track_time_interval(
                self.hass,
                self._async_reconnect_tick,
                timedelta(seconds=RECONNECT_INTERVAL),
            )
        )
        self.hass.async_create_task(self._async_initial_connect())

    async def _async_initial_connect(self) -> None:
        """Try to link after HA restart without blocking setup."""
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(DEVICE_STARTUP_TIMEOUT):
                await self._ready_event.wait()
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac, connectable=True
        )
        if device is None:
            _LOGGER.info(
                "%s not advertising yet after startup; will reconnect on wake",
                self.mac,
            )
            return
        with contextlib.suppress(Exception):
            await self._async_wake_reconnect(device)

    def _poll_interval_seconds(self) -> float:
        if self.config_entry.options.get(CONF_FAST_POLL):
            base = HEAT_POLL_INTERVAL
        else:
            base = POLL_INTERVAL
        if self.data and is_heat_cycle_state(self.data.operating_state):
            return HEAT_POLL_INTERVAL
        return base

    @callback
    def _async_interval_poll(self, now: datetime) -> None:
        if self.hass.is_stopping or self._write_in_progress or self._lock.locked():
            return
        if not self._ble_connected:
            return
        interval = self._poll_interval_seconds()
        if self._last_interval_poll is not None:
            elapsed = (now - self._last_interval_poll).total_seconds()
            if elapsed < interval - 0.05:
                if (
                    interval == POLL_INTERVAL
                    and elapsed >= HEAT_POLL_INTERVAL
                    and self.data is not None
                    and not is_heat_cycle_state(self.data.operating_state)
                ):
                    self.hass.async_create_task(self._async_probe_operating_state())
                return
        self._last_interval_poll = now
        self.hass.async_create_task(self._async_run_interval_poll())

    async def _async_probe_operating_state(self) -> None:
        """One cheap read while idle to catch a session started on the device."""
        if (
            self._write_in_progress
            or self._lock.locked()
            or self.data is None
            or is_heat_cycle_state(self.data.operating_state)
        ):
            return
        try:
            async with self._lock:
                if not self._client.is_connected:
                    return
                state_id = await self._client.bleak.get_operating_state()
        except Exception:
            return
        new_state = operating_state_name(state_id)
        if is_heat_cycle_state(new_state):
            _LOGGER.debug(
                "%s heat cycle detected via probe; switching to %ss poll",
                self.mac,
                HEAT_POLL_INTERVAL,
            )
            self._last_interval_poll = None
            self.hass.async_create_task(self._async_run_interval_poll())

    @callback
    def _async_reconnect_tick(self, _now) -> None:
        if self.hass.is_stopping or self._write_in_progress:
            return
        if self._ble_connected and self._client.is_connected:
            return
        if not self._needs_reconnect and not self._advertising:
            return
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac, connectable=True
        )
        if device is None:
            return
        self._needs_reconnect = True
        self._schedule_reconnect(device)

    async def _async_run_interval_poll(self) -> None:
        previous_data = self.data
        previous_state = (
            previous_data.operating_state if previous_data is not None else None
        )
        self._interval_poll_count += 1
        in_heat = is_heat_cycle_state(previous_state)
        full = self.data is None or (
            not in_heat and self._interval_poll_count % FULL_POLL_EVERY == 0
        )
        try:
            self.data = await self._async_fetch_data(None, full=full)
        except Exception as err:
            _LOGGER.debug("Interval poll failed for %s: %s", self.mac, err)
            self._ble_connected = False
            self._needs_reconnect = True
            return

        self._on_data_updated(previous_data, self.data)
        new_state = self.data.operating_state
        if not is_heat_cycle_state(previous_state) and is_heat_cycle_state(
            new_state
        ):
            _LOGGER.debug(
                "%s entered heat cycle; polling every %ss",
                self.mac,
                HEAT_POLL_INTERVAL,
            )
            self._last_interval_poll = None
        elif is_heat_cycle_state(previous_state) and not is_heat_cycle_state(
            new_state
        ):
            _LOGGER.debug(
                "%s heat cycle finished; polling every %ss",
                self.mac,
                POLL_INTERVAL,
            )
            self._last_interval_poll = None
            with contextlib.suppress(Exception):
                self.data = await self._async_fetch_data(None, full=True)

        self.async_update_listeners()

    @callback
    def _needs_poll(
        self,
        service_info: BluetoothServiceInfoBleak,
        seconds_since_last_poll: float | None,
    ) -> bool:
        if self._needs_reconnect:
            return self.hass.state is CoreState.running
        return (
            self.hass.state is CoreState.running
            and (
                seconds_since_last_poll is None
                or seconds_since_last_poll > DEFAULT_SCAN_INTERVAL
            )
            and bool(
                bluetooth.async_ble_device_from_address(
                    self.hass, service_info.device.address, connectable=True
                )
            )
        )

    async def _async_poll_device(
        self, service_info: BluetoothServiceInfoBleak
    ) -> PuffcoData:
        return await self._async_fetch_data(service_info.device)

    async def _async_fetch_data(
        self, device: BLEDevice | None, *, full: bool = True
    ) -> PuffcoData:
        async with self._lock:
            resolved = (
                bluetooth.async_ble_device_from_address(
                    self.hass, self.mac, connectable=True
                )
                or device
            )
            if resolved is not None:
                self._client.set_ble_device(resolved)
            if not self._client.is_connected:
                await self._client.connect()
            try:
                if full or self.data is None:
                    data = await self._client.fetch_data()
                else:
                    data = await self._client.fetch_data_fast(self.data)
            except Exception:
                self._ble_connected = False
                self._needs_reconnect = True
                await self._client.disconnect()
                raise
            self._mark_online()
            return data

    @callback
    def _async_handle_unavailable(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        self._advertising = False
        # The Peak stops advertising once connected; do not tear down the GATT
        # session when HA only lost sight of adverts.
        if self._ble_connected and self._client.is_connected:
            self.async_update_listeners()
            return
        self._ble_connected = False
        self._needs_reconnect = True
        super()._async_handle_unavailable(service_info)
        self.hass.async_create_task(self._async_drop_connection())

    async def _async_drop_connection(self) -> None:
        async with self._lock:
            await self._client.disconnect()

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        self._ready_event.set()
        self._advertising = True
        force = self._needs_reconnect or not self._client.is_connected
        if force:
            self._last_poll = None
        super()._async_handle_bluetooth_event(service_info, change)
        if force:
            self._schedule_reconnect(service_info.device)

    async def _async_wake_reconnect(self, device: BLEDevice) -> None:
        """Legacy entry point — routes through the reconnect worker."""
        self._needs_reconnect = True
        self._schedule_reconnect(device)

    async def async_wait_ready(self) -> bool:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(DEVICE_STARTUP_TIMEOUT):
                await self._ready_event.wait()
                return True
        return False

    async def async_start_session(self, profile: int | None = None) -> None:
        if (
            self.block_start_while_charging
            and self.data is not None
            and self.data.battery_charging
        ):
            raise HomeAssistantError(
                "Cannot start a session while the Peak is charging"
            )

        async def _write(client):
            if profile is not None:
                await client.bleak.change_profile(profile - 1, current=True)
            await client.start_session()

        await self.async_write(_write)

    async def async_abort_session(self) -> None:
        await self.async_write(lambda client: client.abort_session())

    async def async_set_profile(self, profile: int) -> None:
        idx = profile - 1

        async def _write(client):
            await client.bleak.change_profile(idx, current=True)

        await self.async_write(_write)

    async def async_write(
        self,
        action: Callable[[PuffcoClient], Awaitable[None]],
        *,
        profile_index: int | None = None,
        refresh: bool = True,
    ) -> None:
        self._write_in_progress = True
        previous_data = self.data
        try:
            async with self._lock:
                device = bluetooth.async_ble_device_from_address(
                    self.hass, self.mac, connectable=True
                )
                if device is None and not self._client.is_connected:
                    raise HomeAssistantError(
                        f"Puffco {self.mac} is not currently available"
                    )
                if device is not None:
                    self._client.set_ble_device(device)
                if not self._client.is_connected:
                    await self._client.connect()
                await action(self._client)
                if refresh:
                    self.data = await self._client.fetch_data_fast(
                        self.data, profile_index=profile_index
                    )
                elif self.data is not None and self._client.is_connected:
                    enabled = self._client.bleak.lantern_enabled
                    if enabled is not None:
                        self.data = replace(self.data, lantern_on=bool(enabled))
            self._mark_online()
            if self.data is not None:
                self._on_data_updated(previous_data, self.data)
            if self.data and is_heat_cycle_state(self.data.operating_state):
                self._last_interval_poll = None
            self.async_update_listeners()
        finally:
            self._write_in_progress = False

    async def async_reconnect(self, *, clear_bond: bool = False) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
        self._reconnect_task = None
        self._needs_reconnect = True
        self._ble_connected = False
        async with self._lock:
            if clear_bond:
                self._client.reset_bond_state()
            await self._client.disconnect()
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac, connectable=True
            )
            if device is None:
                raise HomeAssistantError(
                    f"Puffco {self.mac} is not visible. Wake the Peak and close "
                    "the phone app."
                )
            self._client.set_ble_device(device)
            self._pending_ble_device = device
            _LOGGER.info("Manual reconnect to %s (clear_bond=%s)", self.mac, clear_bond)

        await self._async_reconnect_worker()
        if not self._ble_connected:
            raise HomeAssistantError(
                f"Reconnect to {self.mac} failed; check logs for details"
            )

    async def async_shutdown(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
        self._reconnect_task = None
        await self._client.disconnect()
