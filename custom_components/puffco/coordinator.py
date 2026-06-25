"""Active Bluetooth data update coordinator for Puffco."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
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
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BLOCK_START_WHILE_CHARGING,
    CONF_FAST_POLL,
    CONF_IDLE_DISCONNECT,
    CONF_WAKE_ON_COMMAND,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_IDLE_DISCONNECT,
    DEFAULT_WAKE_ON_COMMAND,
    DOMAIN,
    ATTR_OPERATING_STATE,
    EVENT_CHARGING_STARTED,
    EVENT_DISCONNECTED,
    EVENT_SESSION_FINISHED,
    EVENT_SESSION_STARTED,
    FULL_POLL_EVERY,
    HEAT_CYCLE_STATES,
    HEAT_POLL_INTERVAL,
    IDLE_DISCONNECT_SECONDS,
    POLL_INTERVAL,
    RECONNECT_INTERVAL,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_WAKE_DELAY,
    RECONNECT_WAKE_DELAY_ADVERTISING,
    SESSION_START_POLL_ATTEMPTS,
    SESSION_START_POLL_INTERVAL,
    WAKE_ON_COMMAND_POLL,
    WAKE_ON_COMMAND_TIMEOUT,
    is_heat_cycle_state,
)
from .helpers import is_on_dock
from puffco_ble.ble_client import PuffcoBleakClient
from puffco_ble.client import PuffcoClient
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
        self._interval_poll_task: asyncio.Task | None = None
        self._pending_ble_device: BLEDevice | None = None
        self._reconnect_failures = 0
        self._session_listeners: list[Callable[[str, dict], None]] = []
        self._previous_charging: bool | None = None
        self._previous_on_dock: bool | None = None
        self._session_finishes_at: datetime | None = None
        self._session_timer_unsub: Callable[[], None] | None = None
        self._last_seen: datetime | None = None
        self._last_gatt_activity: datetime | None = None
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
    def last_seen(self) -> datetime | None:
        """Last time we heard from the Peak (poll, connect, or advert)."""
        return self._last_seen

    @property
    def is_awake(self) -> bool:
        """True when the Peak is advertising or we hold an active GATT session."""
        return self._advertising or self.ble_connected

    @property
    def commands_reachable(self) -> bool:
        """True when a user command can reach the device (connect or wake via BLE)."""
        return self.is_awake

    @property
    def available(self) -> bool:
        """Stay available with cached data while the Peak sleeps or is connected."""
        if self.data is not None:
            return True
        return self._available

    @property
    def block_start_while_charging(self) -> bool:
        return self.config_entry.options.get(
            CONF_BLOCK_START_WHILE_CHARGING, True
        )

    def heat_seconds_remaining(self) -> float | None:
        """Real-time countdown (local timer), with BLE fallback."""
        if self._session_finishes_at is not None:
            remaining = (
                self._session_finishes_at - dt_util.utcnow()
            ).total_seconds()
            if not math.isfinite(remaining):
                return None
            return max(0.0, round(remaining))
        data = self.data
        if not data:
            return None
        if not is_heat_cycle_state(data.operating_state):
            return 0.0
        if data.state_total_s is None or data.state_elapsed_s is None:
            return None
        if not math.isfinite(data.state_total_s) or not math.isfinite(data.state_elapsed_s):
            return None
        remaining = max(0.0, round(data.state_total_s - data.state_elapsed_s))
        if not math.isfinite(remaining):
            return None
        return remaining

    @property
    def session_finishes_at(self) -> datetime | None:
        """UTC time when the local session countdown reaches zero."""
        return self._session_finishes_at

    @property
    def session_timer_active(self) -> bool:
        return self._session_finishes_at is not None

    @property
    def in_heat_session(self) -> bool:
        """True while preheating, heating, fading, or the local timer is running."""
        if self.session_timer_active:
            return True
        return bool(
            self.data and is_heat_cycle_state(self.data.operating_state)
        )

    @callback
    def _estimate_session_seconds(self, data: PuffcoData) -> float:
        """Best guess for cycle length when starting the local timer."""
        if (
            data.state_total_s is not None
            and data.state_elapsed_s is not None
            and math.isfinite(data.state_total_s)
            and math.isfinite(data.state_elapsed_s)
        ):
            return max(1.0, data.state_total_s - data.state_elapsed_s)
        if data.profile_times_s and len(data.profile_times_s) > data.active_profile:
            profile_time = data.profile_times_s[data.active_profile]
            if profile_time and math.isfinite(profile_time):
                return max(1.0, float(profile_time))
        return 45.0

    @callback
    def _start_session_timer(self, data: PuffcoData) -> None:
        """Start a 1s local countdown when a heat session begins."""
        self._stop_session_timer()
        duration = self._estimate_session_seconds(data)
        if not math.isfinite(duration):
            duration = 45.0
        self._session_finishes_at = dt_util.utcnow() + timedelta(seconds=duration)
        self._session_timer_unsub = async_track_time_interval(
            self.hass,
            self._async_session_timer_tick,
            timedelta(seconds=1),
        )
        _LOGGER.debug(
            "%s local session timer started (~%.0fs)", self.mac, duration
        )

    @callback
    def _sync_session_timer_from_ble(self, data: PuffcoData) -> None:
        """Re-align the local timer when fresh BLE elapsed/total reads arrive."""
        if (
            data.state_total_s is None
            or data.state_elapsed_s is None
            or not math.isfinite(data.state_total_s)
            or not math.isfinite(data.state_elapsed_s)
        ):
            return
        remaining = max(0.0, data.state_total_s - data.state_elapsed_s)
        if not math.isfinite(remaining):
            return
        self._session_finishes_at = dt_util.utcnow() + timedelta(seconds=remaining)
        if self._session_timer_unsub is None:
            self._session_timer_unsub = async_track_time_interval(
                self.hass,
                self._async_session_timer_tick,
                timedelta(seconds=1),
            )

    @callback
    def _async_session_timer_tick(self, _now: datetime) -> None:
        """Push timer sensor updates every second during a session."""
        if self._session_finishes_at is None:
            self._stop_session_timer()
            return
        remaining = (
            self._session_finishes_at - dt_util.utcnow()
        ).total_seconds()
        if remaining <= 0:
            if self.session_timer_active:
                self._finish_session_from_timer()
            else:
                self._stop_session_timer()
            return
        self.async_update_listeners()

    @callback
    def _finish_session_from_timer(self) -> None:
        """Local countdown ended — stop the timer; BLE idle drives session finished."""
        self._stop_session_timer()
        self.async_update_listeners()

    @callback
    def _build_state_event_data(
        self,
        current: PuffcoData,
        prev_state: str | None,
        new_state: str,
    ) -> dict:
        """Event payload aligned with the operating_state sensor."""
        event_data = {
            **self._event_payload(current),
            ATTR_OPERATING_STATE: new_state,
            "operating_state": new_state,
            "previous_state": prev_state,
            "profile": current.active_profile + 1,
            "target_temperature": current.profile_temp_c,
            "in_heat_session": is_heat_cycle_state(new_state),
        }
        if (
            current.state_elapsed_s is not None
            and math.isfinite(current.state_elapsed_s)
        ):
            event_data["state_elapsed_seconds"] = round(current.state_elapsed_s)
        if (
            current.state_total_s is not None
            and math.isfinite(current.state_total_s)
        ):
            event_data["state_total_seconds"] = round(current.state_total_s)
        if is_heat_cycle_state(new_state) and self._session_finishes_at is not None:
            event_data["finishes_at"] = dt_util.as_local(
                self._session_finishes_at
            ).isoformat()
        return event_data

    @callback
    def _stop_session_timer(self) -> None:
        if self._session_timer_unsub is not None:
            self._session_timer_unsub()
            self._session_timer_unsub = None
        self._session_finishes_at = None

    @callback
    def _optimistic_session_start(self) -> None:
        """Reflect session start in HA immediately; BLE confirms in background."""
        if self.data is None or is_heat_cycle_state(self.data.operating_state):
            return
        previous = self.data
        duration = self._estimate_session_seconds(previous)
        current = replace(
            previous,
            operating_state="heat_cycle_preheat",
            state_elapsed_s=0.0,
            state_total_s=duration,
        )
        self.data = current
        self._on_operating_state_change(
            previous, current, previous.operating_state, "heat_cycle_preheat"
        )
        self.async_update_listeners()

    @callback
    def _optimistic_session_abort(self) -> None:
        """Reflect session abort in HA immediately; BLE confirms in background."""
        if self.data is None or not is_heat_cycle_state(self.data.operating_state):
            return
        previous = self.data
        prev_state = previous.operating_state
        current = replace(
            previous,
            operating_state="idle",
            state_elapsed_s=None,
            state_total_s=None,
        )
        self.data = current
        self._stop_session_timer()
        self._on_operating_state_change(previous, current, prev_state, "idle")
        self.async_update_listeners()

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
        try:
            dev_reg = dr.async_get(self.hass)
            if device := dev_reg.async_get_device({(DOMAIN, self.mac)}):
                dev_reg.async_update_device(
                    device.id,
                    model=model,
                    sw_version=data.firmware or device.sw_version,
                    serial_number=data.serial_number or device.serial_number,
                )
        except Exception:
            _LOGGER.warning(
                "Device registry update failed for %s", self.mac, exc_info=True
            )

    @callback
    def _dispatch_session_event(self, event_type: str, data: dict) -> None:
        for listener in self._session_listeners:
            listener(event_type, data)

    def _logbook(self, message: str, name: str | None = None) -> None:
        from homeassistant.components import logbook

        logbook.async_log_entry(
            self.hass,
            name or self.config_entry.title,
            message,
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

        prev_on_dock = (
            is_on_dock(previous.battery_charge_state)
            if previous
            else self._previous_on_dock
        )
        curr_on_dock = is_on_dock(current.battery_charge_state)
        if curr_on_dock and prev_on_dock is not True:
            payload = self._event_payload(current)
            payload["charge_state"] = current.battery_charge_state
            self.hass.bus.async_fire(EVENT_CHARGING_STARTED, payload)
            self._logbook(
                f"On charger ({current.battery_charge_state.replace('_', ' ')})"
            )
        self._previous_charging = current.battery_charging
        self._previous_on_dock = curr_on_dock

        if is_heat_cycle_state(current.operating_state):
            if self._session_finishes_at is None:
                self._start_session_timer(current)
            else:
                self._sync_session_timer_from_ble(current)
        elif self._session_finishes_at is not None:
            self._stop_session_timer()

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
        event_data = self._build_state_event_data(current, prev_state, new_state)

        if not was_heat and now_heat:
            self._start_session_timer(current)
            self.hass.bus.async_fire(EVENT_SESSION_STARTED, event_data)
            self._dispatch_session_event("started", event_data)
            self._logbook(
                f"Heat session started ({new_state.replace('_', ' ')}, profile "
                f"{current.active_profile + 1}, "
                f"{round(current.profile_temp_c) if math.isfinite(current.profile_temp_c) else '?'}°C)"
            )
            if new_state in HEAT_CYCLE_STATES:
                self._dispatch_session_event(new_state, event_data)
        elif was_heat and not now_heat:
            self._stop_session_timer()
            self.hass.bus.async_fire(EVENT_SESSION_FINISHED, event_data)
            self._dispatch_session_event("finished", event_data)
            self._logbook(
                f"Heat session finished ({prev_state.replace('_', ' ') if prev_state else 'heat'} → {new_state})"
            )
        elif (
            was_heat
            and now_heat
            and prev_state != new_state
            and new_state in HEAT_CYCLE_STATES
        ):
            self._dispatch_session_event(new_state, event_data)
            self._logbook(
                f"Heat cycle phase: {prev_state.replace('_', ' ')} → "
                f"{new_state.replace('_', ' ')}"
            )

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
        # Only reconnect immediately when the Peak is still advertising (link
        # flutter). If it went to sleep, wait for a wake advert instead of
        # hammering BLE — that stale reconnect loop often needs pairing mode.
        if self._advertising:
            self._schedule_reconnect()

    @callback
    def _sync_link_state(self) -> None:
        """Clear stale connected flags when the GATT session is already gone."""
        if self._ble_connected and not self._client.is_connected:
            _LOGGER.debug("%s GATT session ended without disconnect callback", self.mac)
            self._ble_connected = False
            self._needs_reconnect = True
            self.async_update_listeners()

    def _idle_disconnect_enabled(self) -> bool:
        return self.config_entry.options.get(
            CONF_IDLE_DISCONNECT, DEFAULT_IDLE_DISCONNECT
        )

    def _should_idle_disconnect(self) -> bool:
        if not self._idle_disconnect_enabled():
            return False
        if not self._ble_connected or not self._client.is_connected:
            return False
        if self.in_heat_session or self._write_in_progress:
            return False
        if self._last_gatt_activity is None:
            return False
        elapsed = (dt_util.utcnow() - self._last_gatt_activity).total_seconds()
        return elapsed >= IDLE_DISCONNECT_SECONDS

    async def _async_idle_disconnect(self) -> None:
        """Release an idle GATT session so the Peak can sleep normally."""
        if not self._should_idle_disconnect():
            return
        _LOGGER.info(
            "%s idle for %ss — releasing BLE link so the Peak can sleep",
            self.mac,
            IDLE_DISCONNECT_SECONDS,
        )
        async with self._lock:
            if not self._client.is_connected:
                self._ble_connected = False
                self._needs_reconnect = True
                self.async_update_listeners()
                return
            self._ble_connected = False
            self._needs_reconnect = True
            self._advertising = False
            await self._client.disconnect()
        self.async_update_listeners()

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
            delay = (
                RECONNECT_WAKE_DELAY_ADVERTISING
                if self._advertising
                else RECONNECT_WAKE_DELAY
            )
            await asyncio.sleep(delay)

        last_err: Exception | None = None
        for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
            device = self._pending_ble_device
            if device is None:
                device = bluetooth.async_ble_device_from_address(
                    self.hass, self.mac, connectable=True
                )
            if device is None:
                _LOGGER.debug(
                    "%s reconnect attempt %s/%s: not visible yet",
                    self.mac,
                    attempt,
                    RECONNECT_MAX_ATTEMPTS,
                )
                if attempt < RECONNECT_MAX_ATTEMPTS:
                    await asyncio.sleep(min(2 * attempt, 6))
                continue
            previous_data = self.data
            try:
                self.data = await self._async_fetch_data(device)
            except Exception as err:
                last_err = err
                self._reconnect_failures += 1
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
            self._reconnect_failures = 0
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
    def _touch_last_seen(self) -> None:
        self._last_seen = dt_util.utcnow()

    @callback
    def _touch_gatt_activity(self) -> None:
        """Mark recent GATT traffic (connect, poll, or command)."""
        self._last_gatt_activity = dt_util.utcnow()
        self._touch_last_seen()

    @callback
    def _mark_online(self) -> None:
        self._ble_connected = True
        self._needs_reconnect = False
        self._available = True
        self._touch_gatt_activity()

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
    def async_request_full_refresh(self) -> None:
        """Schedule a full BLE read after connect settles (profile colors, diagnostics)."""
        if self.hass.is_stopping:
            return

        @callback
        def _deferred(_now: datetime) -> None:
            self.hass.async_create_task(self._async_run_full_refresh_safe())

        self.hass.async_call_later(self.hass, 3, _deferred)

    async def _async_run_full_refresh_safe(self) -> None:
        if self._write_in_progress or self._lock.locked():
            return
        if not self._ble_connected and not self._advertising:
            return
        await self._async_run_full_refresh()

    async def _async_run_full_refresh(self) -> None:
        previous_data = self.data
        try:
            self.data = await self._async_fetch_data(None, full=True)
            with contextlib.suppress(Exception):
                self._on_data_updated(previous_data, self.data)
            self.async_update_listeners()
        except Exception as err:
            _LOGGER.debug("Full refresh for %s failed: %s", self.mac, err)

    @callback
    def _async_interval_poll(self, now: datetime) -> None:
        if self.hass.is_stopping or self._write_in_progress or self._lock.locked():
            return
        self._sync_link_state()
        if not self._ble_connected:
            return
        if self._should_idle_disconnect():
            self.hass.async_create_task(self._async_idle_disconnect())
            return
        interval = self._poll_interval_seconds()
        if self._last_interval_poll is not None:
            elapsed = (now - self._last_interval_poll).total_seconds()
            if elapsed < interval - 0.05:
                return
        self._last_interval_poll = now
        self._schedule_interval_poll()

    @callback
    def _schedule_interval_poll(self) -> None:
        if self._interval_poll_task is not None and not self._interval_poll_task.done():
            return
        self._interval_poll_task = self.hass.async_create_task(
            self._async_run_interval_poll()
        )

    @callback
    def _async_reconnect_tick(self, _now) -> None:
        if self.hass.is_stopping or self._write_in_progress:
            return
        if self._ble_connected and self._client.is_connected:
            return
        if not self._needs_reconnect and not self._advertising:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac, connectable=True
        )
        if device is None:
            return
        self._needs_reconnect = True
        self._schedule_reconnect(device)

    async def _async_preempt_ble_for_write(self) -> None:
        """Cancel in-flight polls/reconnect so commands reach the Peak immediately."""
        tasks: list[asyncio.Task] = []
        for task in (
            self._interval_poll_task,
            self._reconnect_task,
        ):
            if task is not None and not task.done():
                tasks.append(task)
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._interval_poll_task in tasks:
            self._interval_poll_task = None
        if self._reconnect_task in tasks:
            self._reconnect_task = None

    async def _async_resolve_ble_device(self) -> BLEDevice | None:
        """Return a connectable BLE device, optionally waiting for the Peak to wake."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac, connectable=True
        )
        if device is not None or self._client.is_connected:
            return device
        if not self.config_entry.options.get(
            CONF_WAKE_ON_COMMAND, DEFAULT_WAKE_ON_COMMAND
        ):
            return None
        deadline = dt_util.utcnow() + timedelta(seconds=WAKE_ON_COMMAND_TIMEOUT)
        while dt_util.utcnow() < deadline:
            await asyncio.sleep(WAKE_ON_COMMAND_POLL)
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac, connectable=True
            )
            if device is not None:
                self._advertising = True
                self._touch_last_seen()
                return device
        return None

    async def _async_post_write_refresh(
        self, previous_data: PuffcoData | None, profile_index: int | None = None
    ) -> None:
        """Sync HA state after a command without blocking the next write."""
        if self._write_in_progress:
            return
        try:
            async with self._lock:
                if not self._client.is_connected:
                    return
                self.data = await self._client.fetch_data_fast(
                    self.data, profile_index=profile_index
                )
            self._mark_online()
            if self.data is not None:
                with contextlib.suppress(Exception):
                    self._on_data_updated(previous_data, self.data)
            if self.data and is_heat_cycle_state(self.data.operating_state):
                self._last_interval_poll = None
            self.async_update_listeners()
        except Exception as err:
            _LOGGER.debug("Post-write refresh for %s failed: %s", self.mac, err)

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
            try:
                self.data = await self._async_fetch_data(None, full=full)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if previous_data is not None and is_heat_cycle_state(
                    previous_data.operating_state
                ):
                    _LOGGER.debug(
                        "Interval poll failed during heat for %s: %s",
                        self.mac,
                        err,
                    )
                    self.async_update_listeners()
                    return
                _LOGGER.debug("Interval poll failed for %s: %s", self.mac, err)
                self._ble_connected = False
                self._needs_reconnect = True
                return

            with contextlib.suppress(Exception):
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
        finally:
            self._interval_poll_task = None

    @callback
    def _needs_poll(
        self,
        service_info: BluetoothServiceInfoBleak,
        seconds_since_last_poll: float | None,
    ) -> bool:
        if self._ble_connected and self._client.is_connected:
            return False
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
            except Exception as err:
                if self.data is not None and is_heat_cycle_state(
                    self.data.operating_state
                ):
                    _LOGGER.debug(
                        "BLE poll failed during heat for %s; keeping session state",
                        self.mac,
                    )
                    return self.data
                self._ble_connected = False
                self._needs_reconnect = True
                await self._client.disconnect()
                raise err from err
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
        self._touch_last_seen()
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

    async def _async_refresh_until_heat_state(self) -> None:
        """Poll until the Peak reports a heat-cycle state (BLE lags start by ~1s)."""
        if self.data and is_heat_cycle_state(self.data.operating_state):
            return
        for attempt in range(SESSION_START_POLL_ATTEMPTS):
            if attempt > 0:
                await asyncio.sleep(SESSION_START_POLL_INTERVAL)
            previous = self.data
            try:
                async with self._lock:
                    if not self._client.is_connected:
                        device = bluetooth.async_ble_device_from_address(
                            self.hass, self.mac, connectable=True
                        )
                        if device is None:
                            continue
                        self._client.set_ble_device(device)
                        await self._client.connect()
                    self.data = await self._client.fetch_data_fast(self.data)
            except Exception as err:
                _LOGGER.debug("Post-start refresh failed for %s: %s", self.mac, err)
                continue
            if self.data is None:
                continue
            self._on_data_updated(previous, self.data)
            self.async_update_listeners()
            if is_heat_cycle_state(self.data.operating_state):
                return

    async def _async_confirm_on_dock(self) -> bool:
        """Live BLE dock check when cache says on-charger (avoids stale blocks)."""
        await self._async_preempt_ble_for_write()
        device = await self._async_resolve_ble_device()
        try:
            async with self._lock:
                if device is not None:
                    self._client.set_ble_device(device)
                if not self._client.is_connected:
                    await self._client.connect()
                charging, charge_state, charge_eta = (
                    await self._client.read_battery_charge()
                )
                self._touch_gatt_activity()
            if self.data is not None:
                previous = self.data
                self.data = replace(
                    self.data,
                    battery_charging=charging,
                    battery_charge_state=charge_state,
                    charge_eta_seconds=charge_eta,
                )
                self._on_data_updated(previous, self.data)
                self.async_update_listeners()
            return is_on_dock(charge_state)
        except Exception as err:
            _LOGGER.debug(
                "Could not verify dock state for %s before session start: %s",
                self.mac,
                err,
            )
            return False

    async def async_start_session(self, profile: int | None = None) -> None:
        if (
            self.block_start_while_charging
            and self.data is not None
            and is_on_dock(self.data.battery_charge_state)
            and await self._async_confirm_on_dock()
        ):
            raise HomeAssistantError(
                "Cannot start a session while the Peak is on the charger"
            )

        async def _write(client):
            await client.ensure_connected()
            bleak = client.bleak
            if profile is not None:
                target = profile - 1
                if self.data is None or self.data.active_profile != target:
                    await bleak.change_profile(target, current=True)
            await bleak.start_heat_cycle()

        await self.async_write(_write, refresh=False)
        self._optimistic_session_start()
        self.hass.async_create_task(self._async_refresh_until_heat_state())

    async def async_abort_session(self) -> None:
        async def _write(client):
            await client.ensure_connected()
            await client.bleak.abort_heat_cycle()

        await self.async_write(_write, refresh=False)
        self._optimistic_session_abort()

    async def async_boost_session(self) -> None:
        if not self.in_heat_session:
            raise HomeAssistantError("Boost is only available during an active heat session")

        async def _write(client):
            await client.ensure_connected()
            await client.bleak.boost_heat_cycle()

        await self.async_write(_write, refresh=True)

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
        stealth_mode: bool | None = None,
    ) -> None:
        self._write_in_progress = True
        await self._async_preempt_ble_for_write()
        previous_data = self.data
        device = await self._async_resolve_ble_device()
        try:
            async with self._lock:
                if device is None and not self._client.is_connected:
                    raise HomeAssistantError(
                        "Puffco is asleep or out of range — wake it (tap the "
                        "power button) and try again"
                    )
                if device is not None:
                    self._client.set_ble_device(device)
                if not self._client.is_connected:
                    await self._client.connect()
                await action(self._client)
                self._touch_gatt_activity()
                if not refresh and self.data is not None and self._client.is_connected:
                    enabled = self._client.bleak.lantern_enabled
                    if enabled is not None:
                        self.data = replace(self.data, lantern_on=bool(enabled))
                if stealth_mode is not None and self.data is not None:
                    self.data = replace(self.data, stealth_mode=stealth_mode)
            self._mark_online()
            if not refresh and self.data is not None:
                with contextlib.suppress(Exception):
                    self._on_data_updated(previous_data, self.data)
            self.async_update_listeners()
        finally:
            self._write_in_progress = False
        if refresh:
            self.hass.async_create_task(
                self._async_post_write_refresh(previous_data, profile_index)
            )

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
        self._stop_session_timer()
        for task in (
            self._reconnect_task,
            self._interval_poll_task,
        ):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._reconnect_task = None
        self._interval_poll_task = None
        await self._client.disconnect()
        self._async_stop()
