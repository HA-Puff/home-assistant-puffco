"""Low-level Bleak client with Flat and Lorax protocol support."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import math
import struct
import time
from asyncio import Event, ensure_future, wait_for
from datetime import datetime
from typing import Any, Callable

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak.exc import BleakCharacteristicNotFoundError

GATT_READ_TIMEOUT = 8.0
POST_CONNECT_SETTLE_S = 0.5

from puffco_ble.auth import (
    create_lorax_auth_token,
    create_lorax_auth_token_seed_only,
)
from puffco_ble.buffer import Buffer
from puffco_ble.constants import (
    CHAR_UUID2LORAX_PATH,
    Characteristics,
    Constants,
    DEVICE_HANDSHAKE_KEY,
    LanternAnimation,
    LoraxCharacteristics,
    LoraxOpCodes,
    LORAX_PRUNE_HANDLE_MS,
    PROFILE_TO_BYTE_ARRAY,
    PUP_APP_VERSION_CHAR,
    PUP_SERVICE_UUID,
    REVISION_CHARS,
    SILABS_OTA_APP_VERSION_CHAR,
    SILABS_OTA_SERVICE_UUID,
    DeviceCommands,
)
from puffco_ble.encoding import (
    firmware_int_to_string,
    pack_float,
    pack_lorax_mode_command,
    pack_mode_command,
    parse_float,
    finite_float,
    safe_int_from_float,
    safe_int_from_float_bytes,
    parse_lorax_short_number,
    parse_uint32,
)

_LOGGER = logging.getLogger(__name__)


class PuffcoBleakClient(BleakClient):
    """Extended Bleak client implementing Puffco Flat and Lorax GATT access."""

    def __init__(self, address_or_device: str | BLEDevice, **kwargs: Any) -> None:
        super().__init__(address_or_device, **kwargs)
        self.transactions: dict[int, dict[str, Any]] = {}
        self.transaction_responses: dict[str, Any] = {}
        self.sequence_id = 0
        self.use_lorax_protocol = False
        self.lorax_proto_ver: int | None = None
        self.max_payload = 0
        self.max_files = 0
        self.max_cmds = 0
        self.lantern_enabled: bool | None = None
        self.lantern_color: bytearray | None = None
        self.stealth_mode: bool | None = None
        self.device_name = ""
        self.firmware_revision = ""
        self._lorax_reply_indicate = False
        self._lorax_notifications_active = False
        self._already_paired = False

    def reset_pairing_cache(self) -> None:
        """Forget in-session Lorax pairing state (after bond heal / disconnect)."""
        self._already_paired = False
        self.use_lorax_protocol = False
        self._lorax_notifications_active = False
        self.transactions.clear()
        self.transaction_responses.clear()

    # --- GATT routing ---

    async def write_gatt_char(
        self,
        char: str,
        data: bytes | bytearray,
        *,
        response: bool | None = None,
        number: int = 0,
    ) -> None:
        if char in (Characteristics.LANTERN_COLOR, LoraxCharacteristics.LANTERN_COLOR):
            self.lantern_color = bytearray(data)

        if self.use_lorax_protocol and char not in LoraxCharacteristics.PROTOCOL_CHARS:
            lorax_path = CHAR_UUID2LORAX_PATH[char]
            if "%N" in lorax_path:
                lorax_path = lorax_path.replace("%N", str(number))
            if lorax_path.startswith("/u/app/hc/") and lorax_path.endswith("/colr"):
                await self.lorax_write(lorax_path, data)
                return
            await self.lorax_write_short(lorax_path, data)
            return

        await super().write_gatt_char(char, data, response=response)

    async def read_gatt_char(self, char: str, **kwargs: Any) -> bytearray:
        if self.use_lorax_protocol:
            if char in LoraxCharacteristics.PROTOCOL_CHARS:
                data = await super().read_gatt_char(char, **kwargs)
            else:
                lorax_path = CHAR_UUID2LORAX_PATH[char]
                if "%N" in lorax_path:
                    index = kwargs.pop("number", 0) or 0
                    lorax_path = lorax_path.replace("%N", str(index))
                data = await self.lorax_read_short(lorax_path)
        else:
            data = await super().read_gatt_char(char, **kwargs)

        if char in (Characteristics.LANTERN_COLOR, LoraxCharacteristics.LANTERN_COLOR):
            self.lantern_color = bytearray(data)
        return data

    # --- Lorax protocol ---

    def _char_available(self, char_uuid: str) -> bool:
        if not self.services:
            return False
        try:
            self.services.get_characteristic(char_uuid)
            return True
        except BleakCharacteristicNotFoundError:
            return False

    def _ensure_connected(self, step: str) -> None:
        if not self.is_connected:
            raise BleakError(f"Not connected during Lorax init ({step})")

    async def _read_gatt_char_timed(
        self, char_uuid: str, *, timeout: float = GATT_READ_TIMEOUT
    ) -> bytearray:
        try:
            return await wait_for(
                super().read_gatt_char(char_uuid), timeout=timeout
            )
        except TimeoutError as err:
            raise BleakError(f"GATT read timed out ({char_uuid})") from err

    def _next_sequence_id(self) -> int:
        self.sequence_id = (self.sequence_id + 1) % 65535
        return self.sequence_id

    @staticmethod
    def _make_command(sequence_id: int, opcode: int, payload: bytes | None) -> bytes:
        buf = Buffer(3)
        buf.writeUInt16LE(sequence_id, 0)
        buf.writeUInt8(opcode, 2)
        if payload:
            return bytes(buf.data + payload)
        return bytes(buf.data)

    async def _send_lorax_command(self, cmd: bytes) -> None:
        _LOGGER.debug("Lorax command write (%s bytes): %s", len(cmd), cmd.hex())
        # Puffco Lorax command char is write-without-response only (app writeChar ... false).
        try:
            await super().write_gatt_char(
                LoraxCharacteristics.LORAX_COMMAND, cmd, response=False
            )
        except BleakError as err:
            _LOGGER.debug(
                "Lorax command write-without-response failed, trying with response: %s",
                err,
            )
            await super().write_gatt_char(
                LoraxCharacteristics.LORAX_COMMAND, cmd, response=True
            )
        await asyncio.sleep(0.05)

    async def _lorax_command_and_wait(
        self,
        opcode: int,
        payload: bytes | None,
        *,
        timeout: float = 10.0,
        min_reply_len: int = 0,
    ) -> bytes | None:
        """Send a Lorax opcode and wait for a matching reply notification."""
        done = Event()
        holder: list[bytes | None] = [None]

        def on_reply(data: bytes) -> None:
            if min_reply_len and len(data) < min_reply_len:
                return
            holder[0] = data
            done.set()

        tx = self._make_transaction(opcode, None, payload, callback=on_reply)
        await self._send_lorax_command(tx["cmd"])
        try:
            await wait_for(done.wait(), timeout=timeout)
        except TimeoutError:
            self.transactions.pop(tx["sequenceId"], None)
            return None
        return holder[0]

    async def _stop_lorax_notifications(self) -> None:
        if not self._lorax_notifications_active:
            return
        with contextlib.suppress(BleakError, OSError):
            await self.stop_notify(LoraxCharacteristics.LORAX_REPLY)
        with contextlib.suppress(BleakError, OSError):
            await self.stop_notify(LoraxCharacteristics.LORAX_EVENT)
        self._lorax_notifications_active = False

    async def _ensure_lorax_notifications(
        self, *, reply_indicate: bool | None = None
    ) -> None:
        await self._stop_lorax_notifications()

        reply_char = self.services.get_characteristic(
            LoraxCharacteristics.LORAX_REPLY
        )
        props = list(reply_char.properties)
        supports_notify = "notify" in props
        supports_indicate = "indicate" in props

        # Honor caller hint, but never request a mode the characteristic lacks.
        if reply_indicate is None:
            reply_indicate = self._lorax_reply_indicate
        if reply_indicate and not supports_indicate:
            reply_indicate = False
        if not reply_indicate and not supports_notify and supports_indicate:
            reply_indicate = True
        self._lorax_reply_indicate = reply_indicate

        _LOGGER.info(
            "Lorax reply char handle=%04X properties=%s (subscribe %s)",
            reply_char.handle,
            props,
            "indicate" if reply_indicate else "notify",
        )

        notify_kwargs: dict[str, Any] = {}
        if reply_indicate:
            notify_kwargs["force_indicate"] = True
        await self.start_notify(
            LoraxCharacteristics.LORAX_REPLY,
            self._lorax_reply_handler,
            **notify_kwargs,
        )
        await self.start_notify(
            LoraxCharacteristics.LORAX_EVENT, self._lorax_event_handler
        )
        self._lorax_notifications_active = True
        _LOGGER.debug(
            "Lorax notifications active (reply=%s, event=notify)",
            "indicate" if reply_indicate else "notify",
        )
        await asyncio.sleep(0.3)

    async def _ensure_bonded(self) -> bool:
        """Bond/encrypt the link so the Peak delivers Lorax reply notifications.

        Web Bluetooth and Android pair automatically; on WinRT we must request
        it explicitly or the device silently drops notifications.
        """
        try:
            if getattr(self, "_already_paired", False):
                return True
            _LOGGER.info("Lorax init: bonding (OS pairing) for encrypted link...")
            await self.pair()
            self._already_paired = True
            _LOGGER.info("Bond result: paired (encrypted link)")
            return True
        except (BleakError, OSError, NotImplementedError) as err:
            _LOGGER.warning("Bonding attempt failed/unsupported: %s", err)
            return False

    async def _lorax_notifications_probe(self) -> bool:
        """Return True if GET_LIMITS receives a reply on the current subscription."""
        reply = await self._lorax_command_and_wait(
            LoraxOpCodes.GET_LIMITS, None, timeout=5, min_reply_len=6
        )
        if reply is None:
            return False
        buf = Buffer(reply)
        self.max_payload = buf.readUInt16LE(0)
        self.max_files = buf.readUInt16LE(2)
        self.max_cmds = buf.readUInt16LE(4)
        _LOGGER.info(
            "Lorax limits payload=%s files=%s cmds=%s",
            self.max_payload,
            self.max_files,
            self.max_cmds,
        )
        return True

    async def _trigger_bond(
        self, timeout_s: float = 10.0, retry_delay_s: float = 0.5
    ) -> None:
        """Best-effort bond trigger (Android app path; web v3.6.26 skips if absent)."""
        candidates = (
            (SILABS_OTA_APP_VERSION_CHAR, "silabs OTA"),
            (PUP_APP_VERSION_CHAR, "PUP"),
        )
        available = [
            (char_uuid, label)
            for char_uuid, label in candidates
            if self._char_available(char_uuid)
        ]
        if not available:
            _LOGGER.info(
                "Bond trigger skipped (bootloader services not discovered)"
            )
            return

        deadline = time.monotonic() + timeout_s
        for char_uuid, label in available:
            _LOGGER.info("Bond trigger: reading %s...", label)
            while time.monotonic() < deadline:
                try:
                    await self._read_gatt_char_timed(char_uuid, timeout=3.0)
                    _LOGGER.info("Bond trigger read OK (%s)", label)
                    return
                except BleakError as err:
                    if not self.is_connected or time.monotonic() >= deadline:
                        _LOGGER.debug("Bond trigger read failed (%s): %s", label, err)
                        break
                    await asyncio.sleep(retry_delay_s)
        _LOGGER.info("Bond trigger unavailable; continuing without it")

    async def _setup_sticky_prune(self) -> None:
        """Lorax v1+ sticky handle prune (app v3.6.26 setupStickyPrune)."""
        n = round(LORAX_PRUNE_HANDLE_MS / 1.25)
        payload = bytes([1, n & 0xFF, (n >> 8) & 0xFF])
        reply = await self._lorax_command_and_wait(
            LoraxOpCodes.PRUNE_FILE_HANDLES, payload, timeout=15
        )
        if reply is None:
            _LOGGER.warning("Lorax sticky prune timed out; continuing")
        else:
            _LOGGER.debug("Lorax sticky prune acknowledged")

    def _lorax_reply_handler(self, _characteristic: Any, data: bytearray) -> None:
        _LOGGER.debug("Lorax reply (%s bytes): %s", len(data), data.hex())
        try:
            buffer = Buffer(data)
            sequence_id = buffer.readUInt16LE(0)
            error_code = buffer.readUInt8(2)
            transaction = self.transactions.pop(sequence_id, None)

            if not transaction:
                _LOGGER.debug("Lorax reply for unknown sequence %s", sequence_id)
                return

            opcode = transaction["opcode"]
            path = transaction["path"]
            if error_code:
                _LOGGER.warning(
                    "Lorax error %s seq=%s op=%s path=%s",
                    error_code,
                    sequence_id,
                    opcode,
                    path,
                )
                if transaction["flag"]:
                    self.transaction_responses[f"{sequence_id}-{path}"] = None
                    transaction["deferred"]()
                return

            payload = data[3:]
            if path == LoraxCharacteristics.SOFTWARE_REVISION:
                rev = parse_uint32(payload)
                payload = firmware_int_to_string(rev)

            callback = transaction["deferred"]
            if transaction["flag"]:
                self.transaction_responses[f"{sequence_id}-{path}"] = payload
                callback()
                return

            if callback is None:
                return

            args = transaction["args"] or ()
            if inspect.iscoroutinefunction(callback):
                task = asyncio.create_task(callback(payload, *args))

                def _log_callback_error(done: asyncio.Task) -> None:
                    if done.cancelled():
                        return
                    exc = done.exception()
                    if exc is not None:
                        _LOGGER.error(
                            "Lorax callback failed for op=%s path=%s",
                            opcode,
                            path,
                            exc_info=exc,
                        )

                task.add_done_callback(_log_callback_error)
            else:
                callback(payload, *args)
        except Exception:
            _LOGGER.exception("Lorax reply handler error")

    @staticmethod
    def _lorax_event_handler(*_args: Any, **_kwargs: Any) -> None:
        _LOGGER.debug("Lorax event received")

    async def _read_lorax_version_with_retry(
        self, attempts: int = 4, delay_s: float = 0.25
    ) -> bytearray | None:
        """Read the Lorax version char ASAP to keep an idle link from dropping."""
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            if not self.is_connected:
                _LOGGER.debug("Version read: link down before attempt %s", attempt)
                return None
            try:
                return await self._read_gatt_char_timed(
                    LoraxCharacteristics.LORAX_VERSION, timeout=3.0
                )
            except (BleakError, OSError) as err:
                last_err = err
                if not self.is_connected:
                    return None
                _LOGGER.debug(
                    "Version read attempt %s/%s failed: %s", attempt, attempts, err
                )
                await asyncio.sleep(delay_s)
        _LOGGER.debug("Version read exhausted retries: %s", last_err)
        return None

    async def init_lorax_protocol(self) -> bool:
        # App v3.6.26 web/desktop: version -> notifications -> sticky prune -> limits -> auth
        # (No bond-trigger reads — Android-only and Silabs OTA reads drop WinRT sessions.)
        #
        # An idle (already-bonded) Peak drops a freshly-connected link within ~0.5s
        # if the central performs no GATT operation (WinRT only finalises the
        # connection once we request info). So read the version IMMEDIATELY with
        # short retries instead of sleeping first — that read both detects the
        # protocol and keeps the link alive.
        _LOGGER.info("Lorax init: reading protocol version...")
        version_data = await self._read_lorax_version_with_retry()
        if version_data is None:
            _LOGGER.error("Lorax version read failed (link dropped before settle)")
            return False
        if len(version_data) < 2:
            _LOGGER.error("Invalid Lorax version response (%s bytes)", len(version_data))
            return False
        self.lorax_proto_ver = struct.unpack("<H", bytes(version_data[:2]))[0]
        if self.lorax_proto_ver > 255:
            _LOGGER.error("Unsupported Lorax version %s", self.lorax_proto_ver)
            return False
        _LOGGER.info("Lorax protocol version %s", self.lorax_proto_ver)

        self.use_lorax_protocol = True
        limits_ok = False

        # Strategy matrix: most Windows failures are "subscribed but no replies",
        # which is the device refusing notifications on an unbonded link. We try
        # (bond?, subscribe-mode) combinations until GET_LIMITS actually replies.
        strategies = [
            ("notify", True),   # Windows requires bonded link for Lorax replies
            ("notify", False),  # fallback if already bonded in OS settings
        ]
        for sub_mode, do_bond in strategies:
            self._ensure_connected("notifications")
            if do_bond:
                await self._ensure_bonded()

            _LOGGER.info(
                "Lorax init: enabling notifications (mode=%s, bonded=%s)...",
                sub_mode,
                do_bond,
            )
            try:
                await self._ensure_lorax_notifications(
                    reply_indicate=(sub_mode == "indicate")
                )
            except (OSError, BleakError) as err:
                _LOGGER.error("Failed to start Lorax notifications: %s", err)
                continue

            if self.lorax_proto_ver != 0:
                _LOGGER.info("Lorax init: sticky handle prune...")
                self._ensure_connected("sticky prune")
                await self._setup_sticky_prune()

            _LOGGER.info("Lorax init: requesting protocol limits...")
            self._ensure_connected("get limits")
            if await self._lorax_notifications_probe():
                limits_ok = True
                break

            _LOGGER.warning(
                "Lorax replies not received (mode=%s, bonded=%s); trying next strategy",
                sub_mode,
                do_bond,
            )

        if not limits_ok:
            self.max_payload = max(getattr(self, "mtu_size", 247) - 7, 20)
            self.max_files = 32
            self.max_cmds = 32
            _LOGGER.warning(
                "GET_LIMITS timed out on notify and indicate; continuing with payload=%s",
                self.max_payload,
            )

        auth_done = Event()
        auth_error: list[str] = []
        if not await self._lorax_authenticate(auth_done, auth_error):
            _LOGGER.error(
                "Lorax auth timed out (%s)",
                auth_error[0] if auth_error else "no reply",
            )
            return False
        _LOGGER.info("Lorax authentication succeeded")
        return True

    async def _lorax_authenticate(
        self, done: Event, auth_error: list[str] | None = None
    ) -> bool:
        errors = auth_error if auth_error is not None else []

        seed_reply = await self._lorax_command_and_wait(
            LoraxOpCodes.GET_ACCESS_SEED, None, timeout=10, min_reply_len=16
        )
        if seed_reply is None:
            errors.append("GET_ACCESS_SEED timed out")
            return False

        seed = bytes(seed_reply)[:16]
        if len(seed) < 16:
            seed = seed.ljust(16, b"\x00")
        _LOGGER.debug("Lorax access seed received (%s bytes)", len(seed))

        for label, token_fn in (
            ("handshake2", create_lorax_auth_token),
            ("seed-only", create_lorax_auth_token_seed_only),
        ):
            token = token_fn(seed)
            unlock_reply = await self._lorax_command_and_wait(
                LoraxOpCodes.UNLOCK_ACCESS,
                bytes(token),
                timeout=5,
            )
            if unlock_reply is not None:
                _LOGGER.debug("Lorax UNLOCK_ACCESS succeeded (%s)", label)
                done.set()
                return True
            errors.append(f"unlock failed ({label})")

        errors.append("all unlock methods failed")
        return False

    def _make_transaction(
        self,
        opcode: int,
        path: str | None,
        payload: bytes | None,
        callback: Callable | None = None,
        args: tuple | None = None,
        flag: bool = False,
    ) -> dict[str, Any]:
        tx_id = self._next_sequence_id()
        cmd = self._make_command(tx_id, opcode, payload)
        transaction = {
            "sequenceId": tx_id,
            "opcode": opcode,
            "path": path or "",
            "cmd": cmd,
            "deferred": callback,
            "args": args,
            "flag": flag,
        }
        self.transactions[tx_id] = transaction
        return transaction

    @staticmethod
    def _write_short_cmd(a: int, b: int, path: str, data: bytes) -> bytes:
        header = Buffer(3)
        header.writeUInt16LE(a, 0)
        header.writeUInt8(b, 2)
        path_bytes = path.encode() if isinstance(path, str) else path
        return bytes(header.data + path_bytes + bytearray(1) + data)

    async def lorax_write_short(self, path: str, data: bytes | bytearray) -> None:
        bp = 4 if path.endswith("/name") else 0
        payload = self._write_short_cmd(0, bp, path, bytes(data))
        tx = self._make_transaction(LoraxOpCodes.WRITE_SHORT, path, payload)
        await self._send_lorax_command(tx["cmd"])

    @staticmethod
    def _write_cmd(data: bytes) -> bytes:
        header = Buffer(4)
        header.writeUInt16LE(0, 0)
        header.writeUInt16LE(0, 2)
        return bytes(header.data + data)

    async def lorax_write(self, path: str, data: bytes | bytearray) -> None:
        payload = self._write_cmd(bytes(data))
        tx = self._make_transaction(LoraxOpCodes.WRITE, path, payload)
        await self._send_lorax_command(tx["cmd"])

    @staticmethod
    def _read_short_cmd(max_payload: int, path: str) -> bytes:
        header = Buffer(4)
        header.writeUInt16LE(0, 0)
        header.writeUInt16LE(max_payload, 2)
        path_bytes = path.encode() if isinstance(path, str) else path
        return bytes(header.data + path_bytes)

    async def lorax_read_short(self, path: str) -> bytearray:
        resp = Event()
        payload = self._read_short_cmd(self.max_payload, path)
        tx = self._make_transaction(
            LoraxOpCodes.READ_SHORT, path, payload, callback=resp.set, flag=True
        )
        ensure_future(
            super().write_gatt_char(
                LoraxCharacteristics.LORAX_COMMAND, tx["cmd"], response=False
            )
        )
        await resp.wait()
        result = self.transaction_responses.pop(f"{tx['sequenceId']}-{path}")
        if result is None:
            raise BleakError(f"Lorax read failed for path {path}")
        if isinstance(result, (bytes, bytearray)):
            return bytearray(result)
        if isinstance(result, str):
            return bytearray(result.encode())
        return bytearray(result)

    # --- Flat auth ---

    async def authenticate_flat(self) -> None:
        from puffco_ble.auth import create_flat_auth_token

        seed = await super().read_gatt_char(Characteristics.ACCESS_SEED_KEY)
        token = create_flat_auth_token(seed)
        await super().write_gatt_char(Characteristics.ACCESS_SEED_KEY, token)

    # --- Device operations ---

    async def send_mode_command(self, command: DeviceCommands | int) -> None:
        if self.use_lorax_protocol:
            data = pack_lorax_mode_command(command)
        else:
            data = pack_mode_command(command)
        await self.write_gatt_char(Characteristics.MODE_COMMAND, data)

    async def get_firmware_revision(self) -> str:
        if self.use_lorax_protocol:
            data = await self.read_gatt_char(Characteristics.SOFTWARE_REVISION)
            if isinstance(data, (bytes, bytearray)) and len(data) >= 4:
                return firmware_int_to_string(parse_uint32(data))
            return data.decode() if isinstance(data, (bytes, bytearray)) else str(data)
        raw = await self.read_gatt_char(Characteristics.SOFTWARE_REVISION)
        return raw.decode().strip()

    async def get_device_model(self, *, return_name: bool = False) -> str:
        raw = await self.read_gatt_char(Characteristics.MODEL_NUMBER)
        if self.use_lorax_protocol:
            if len(raw) >= 4:
                model_key = str(parse_uint32(raw))
            elif raw:
                model_key = str(raw[0])
            else:
                model_key = "0"
        else:
            model_key = raw.decode().strip()
        if return_name:
            from puffco_ble.constants import PEAK_PRO_MODELS

            return PEAK_PRO_MODELS.get(model_key, "Unknown Puffco")
        return model_key

    async def get_device_name(self) -> str:
        raw = await self.read_gatt_char(Characteristics.DEVICE_NAME)
        return raw.decode().strip("\x00")

    async def get_battery_percentage(self) -> int:
        return safe_int_from_float_bytes(
            await self.read_gatt_char(Characteristics.BATTERY_SOC)
        )

    async def get_battery_charge_state(self) -> int:
        data = await self.read_gatt_char(Characteristics.BATTERY_CHARGE_STATE)
        if self.use_lorax_protocol:
            return int.from_bytes(data, "little") if data else 0
        return safe_int_from_float_bytes(data)

    async def get_battery_charge_eta_seconds(
        self, state_id: int | None = None
    ) -> float | None:
        if state_id is None:
            state_id = await self.get_battery_charge_state()
        from puffco_ble.encoding import is_battery_charging

        if not is_battery_charging(state_id):
            return None
        raw = finite_float(
            await self.read_gatt_char(Characteristics.BATTERY_CHARGE_FULL_ETA)
        )
        return raw

    async def get_total_dab_count(self) -> int:
        return safe_int_from_float_bytes(
            await self.read_gatt_char(Characteristics.TOTAL_DAB_COUNT)
        )

    async def get_trip_dab_count(self) -> int:
        return safe_int_from_float_bytes(
            await self.read_gatt_char(Characteristics.TRIP_HEAT_CYCLES)
        )

    async def get_daily_dab_count(self) -> float:
        raw = finite_float(
            await self.read_gatt_char(Characteristics.DABS_PER_DAY)
        )
        return round(raw, 1) if raw is not None else 0.0

    async def get_heater_temp_c(self) -> float | None:
        return finite_float(await self.read_gatt_char(Characteristics.HEATER_TEMP))

    async def get_state_elapsed_time(self) -> float | None:
        return finite_float(
            await self.read_gatt_char(Characteristics.STATE_ELAPSED_TIME)
        )

    async def get_state_total_time(self) -> float | None:
        return finite_float(
            await self.read_gatt_char(Characteristics.STATE_TOTAL_TIME)
        )

    async def get_operating_state(self) -> int:
        data = await self.read_gatt_char(Characteristics.OPERATING_STATE)
        if self.use_lorax_protocol:
            return int.from_bytes(data, "little") if data else 0
        return safe_int_from_float_bytes(data)

    async def get_profile(self) -> int:
        data = await self.read_gatt_char(Characteristics.PROFILE_CURRENT)
        if self.use_lorax_protocol:
            return int.from_bytes(data, "little") if data else 0
        raw = finite_float(data)
        return safe_int_from_float(round(raw), default=0) if raw is not None else 0

    async def change_profile(self, profile: int, *, current: bool = False) -> None:
        if not self.use_lorax_protocol:
            await self.write_gatt_char(
                Characteristics.PROFILE, bytearray([profile, 0, 0, 0])
            )
        if current:
            if self.use_lorax_protocol:
                data = profile.to_bytes(1, "little")
            else:
                data = PROFILE_TO_BYTE_ARRAY[profile]
            await self.write_gatt_char(Characteristics.PROFILE_CURRENT, data)

    async def set_profile_temp(self, temperature_c: float, profile: int) -> None:
        await self.change_profile(profile)
        await self.write_gatt_char(
            Characteristics.PROFILE_PREHEAT_TEMP,
            pack_float(temperature_c),
            number=profile,
        )

    async def get_profile_temp(self, profile: int) -> float:
        await self.change_profile(profile)
        raw = finite_float(
            await self.read_gatt_char(
                Characteristics.PROFILE_PREHEAT_TEMP, number=profile
            )
        )
        return raw if raw is not None else 0.0

    async def set_profile_time(self, seconds: float, profile: int) -> None:
        await self.change_profile(profile)
        await self.write_gatt_char(
            Characteristics.PROFILE_PREHEAT_TIME,
            pack_float(seconds),
            number=profile,
        )

    async def get_profile_time(self, profile: int) -> float:
        await self.change_profile(profile)
        raw = finite_float(
            await self.read_gatt_char(
                Characteristics.PROFILE_PREHEAT_TIME, number=profile
            )
        )
        return raw if raw is not None else 0.0

    async def boost_heat_cycle(self) -> None:
        await self.send_mode_command(DeviceCommands.HEAT_CYCLE_BOOST)

    async def get_boost_temp(self, profile: int) -> float:
        await self.change_profile(profile)
        raw = finite_float(
            await self.read_gatt_char(Characteristics.BOOST_TEMP, number=profile)
        )
        return raw if raw is not None else 0.0

    async def set_boost_temp(self, profile: int, celsius: float) -> None:
        await self.change_profile(profile)
        await self.write_gatt_char(
            Characteristics.BOOST_TEMP,
            pack_float(celsius),
            number=profile,
        )

    async def get_boost_time(self, profile: int) -> float:
        await self.change_profile(profile)
        raw = finite_float(
            await self.read_gatt_char(Characteristics.BOOST_TIME, number=profile)
        )
        return raw if raw is not None else 0.0

    async def set_boost_time(self, profile: int, seconds: float) -> None:
        await self.change_profile(profile)
        await self.write_gatt_char(
            Characteristics.BOOST_TIME,
            pack_float(seconds),
            number=profile,
        )

    async def get_profile_name(self, profile: int) -> str:
        raw = await self.read_gatt_char(Characteristics.PROFILE_NAME, number=profile)
        return raw.decode("utf-8", errors="ignore").strip("\x00")

    async def set_profile_name(self, profile: int, name: str) -> None:
        await self.write_gatt_char(
            Characteristics.PROFILE_NAME,
            bytearray(name.encode("utf-8")[:32]),
            number=profile,
        )

    async def get_profile_color(self, profile: int) -> tuple[int, int, int]:
        from puffco_ble.encoding import parse_profile_color

        raw = await self.read_gatt_char(Characteristics.PROFILE_COLOR, number=profile)
        return parse_profile_color(raw)

    async def set_profile_color(self, profile: int, r: int, g: int, b: int) -> None:
        from puffco_ble.encoding import pack_static_lantern_color

        await self.write_gatt_char(
            Characteristics.PROFILE_COLOR,
            pack_static_lantern_color(r, g, b),
            number=profile,
        )

    async def get_chamber_type(self) -> int:
        data = await self.read_gatt_char(Characteristics.CHAMBER_TYPE)
        if self.use_lorax_protocol:
            return int.from_bytes(data, "little") if data else 0
        return safe_int_from_float_bytes(data)

    async def get_approx_dabs_remaining(self) -> int:
        data = await self.read_gatt_char(Characteristics.APPROX_DABS_REMAINING)
        if self.use_lorax_protocol:
            value = parse_lorax_short_number(data, max_reasonable=10_000)
            return safe_int_from_float(value) if value is not None else 0
        return safe_int_from_float_bytes(data)

    async def get_uptime_seconds(self) -> float:
        data = await self.read_gatt_char(Characteristics.UPTIME)
        if self.use_lorax_protocol:
            value = parse_lorax_short_number(data, max_reasonable=100_000_000)
            return value if value is not None and math.isfinite(value) else 0.0
        raw = finite_float(data)
        return raw if raw is not None else 0.0

    async def get_total_heat_cycle_time(self) -> float:
        data = await self.read_gatt_char(Characteristics.TOTAL_HEAT_CYCLE_TIME)
        if self.use_lorax_protocol:
            value = parse_lorax_short_number(data, max_reasonable=100_000_000)
            return value if value is not None and math.isfinite(value) else 0.0
        raw = finite_float(data)
        return raw if raw is not None else 0.0

    async def get_serial_number(self) -> str:
        raw = await self.read_gatt_char(Characteristics.SERIAL_NUMBER)
        return raw.decode("utf-8", errors="ignore").strip("\x00")

    async def get_led_brightness_segments(self) -> tuple[int, int, int, int]:
        data = await self.read_gatt_char(Characteristics.LANTERN_BRIGHTNESS)
        if len(data) >= 4:
            return (int(data[0]), int(data[1]), int(data[2]), int(data[3]))
        val = int(max(data)) if data else 255
        return (val, val, val, val)

    async def set_led_brightness_segments(
        self, ring: int, glass: int, main: int, battery: int
    ) -> None:
        vals = [
            min(Constants.BRIGHTNESS_MAX, max(Constants.BRIGHTNESS_MIN, v))
            for v in (ring, glass, main, battery)
        ]
        await self.write_gatt_char(Characteristics.LANTERN_BRIGHTNESS, bytearray(vals))

    async def set_stealth_mode(self, enabled: bool) -> None:
        if enabled == self.stealth_mode:
            return
        from puffco_ble.encoding import pack_lantern_on

        await self.write_gatt_char(
            Characteristics.STEALTH_STATUS,
            pack_lantern_on(enabled, lorax=self.use_lorax_protocol),
        )
        self.stealth_mode = enabled

    async def get_stealth_mode(self) -> bool:
        data = await self.read_gatt_char(Characteristics.STEALTH_STATUS)
        if not data:
            return self.stealth_mode if self.stealth_mode is not None else False
        # Lorax exposes stealth as a 1-byte flag; Flat firmware uses a float32.
        if self.use_lorax_protocol or len(data) < 4:
            value = bool(data[0])
        else:
            value = bool(safe_int_from_float_bytes(data))
        self.stealth_mode = value
        return value

    async def send_lantern_status(self, enabled: bool) -> None:
        if enabled == self.lantern_enabled:
            return
        self.lantern_enabled = enabled
        from puffco_ble.encoding import pack_lantern_on

        await self.write_gatt_char(
            Characteristics.LANTERN_STATUS,
            pack_lantern_on(enabled, lorax=self.use_lorax_protocol),
        )

    async def send_lantern_color(self, r: int, g: int, b: int, mode: int = 1) -> None:
        from puffco_ble.encoding import pack_static_lantern_color

        await self.write_gatt_char(
            Characteristics.LANTERN_COLOR,
            pack_static_lantern_color(r, g, b, mode=mode),
        )

    async def send_lantern_color_bytes(self, data: bytes | bytearray) -> None:
        await self.write_gatt_char(
            Characteristics.LANTERN_COLOR, bytearray(data)
        )

    async def send_lantern_time(self, seconds: float) -> None:
        from puffco_ble.encoding import pack_float

        await self.write_gatt_char(
            Characteristics.LANTERN_TIME, bytearray(pack_float(seconds))
        )

    async def send_lantern_animation(self, anim: str, enabled: bool) -> None:
        if enabled:
            data = getattr(LanternAnimation, anim.upper(), None)
            if not data:
                raise ValueError(f"Unknown animation {anim!r}")
        else:
            profile = await self.get_profile()
            color = await self.read_gatt_char(
                Characteristics.PROFILE_COLOR, number=profile
            )
            data = bytearray([*color[:3], 0, 1, 0, 0, 0])
        await self.write_gatt_char(Characteristics.LANTERN_COLOR, data)

    async def get_lantern_brightness(self) -> int:
        data = await self.read_gatt_char(Characteristics.LANTERN_BRIGHTNESS)
        return max(data)

    async def send_lantern_brightness(self, value: int) -> None:
        from puffco_ble.encoding import clamp_byte

        val = clamp_byte(value)
        await self.write_gatt_char(
            Characteristics.LANTERN_BRIGHTNESS, bytearray([val] * 4)
        )

    async def start_heat_cycle(self) -> None:
        await self.send_mode_command(DeviceCommands.HEAT_CYCLE_START)

    async def abort_heat_cycle(self) -> None:
        await self.send_mode_command(DeviceCommands.HEAT_CYCLE_ABORT)

    async def get_device_birthday(self) -> str:
        raw = await self.read_gatt_char(Characteristics.DEVICE_BIRTHDAY)
        if self.use_lorax_protocol:
            text = bytes(raw).decode("utf-8", errors="ignore").strip("\x00").strip()
            if len(text) >= 10 and text[4] == "-" and text[7] == "-":
                return text[:10]
            ts = parse_lorax_short_number(raw, max_reasonable=2_000_000_000)
            if ts is not None and ts >= 1_000_000_000:
                try:
                    return str(datetime.fromtimestamp(safe_int_from_float(ts)).date())
                except (OSError, OverflowError, ValueError):
                    return text
            return text
        try:
            ts = parse_uint32(raw)
            return str(datetime.fromtimestamp(ts).date())
        except (OSError, OverflowError, ValueError):
            return ""
