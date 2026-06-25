"""Config flow for Puffco integration."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
from typing import Any

# Ensure the vendored puffco_ble package (under _vendor/) is importable as a
# top-level module (see __init__.py). Redundant if the package __init__ already
# ran, but keeps the flow loadable in any import order.
_VENDORED_DIR = os.path.join(os.path.dirname(__file__), "_vendor")
if _VENDORED_DIR not in sys.path:
    sys.path.insert(0, _VENDORED_DIR)

import voluptuous as vol
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_MAC
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_BLOCK_START_WHILE_CHARGING,
    CONF_FAST_POLL,
    CONF_IDLE_DISCONNECT,
    CONF_SHOW_DIAGNOSTICS,
    CONF_WAKE_ON_COMMAND,
    DEFAULT_BLOCK_START_WHILE_CHARGING,
    DEFAULT_FAST_POLL,
    DEFAULT_IDLE_DISCONNECT,
    DEFAULT_SHOW_DIAGNOSTICS,
    DEFAULT_WAKE_ON_COMMAND,
    DOMAIN,
)
from .coordinator import CannotConnect, validate_connection
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from puffco_ble.protocol import is_peak_pro_advertisement

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

OPTION_SCAN = "__scan__"
OPTION_MANUAL = "__manual__"
SCAN_TIMEOUT_S = 15


def _ble_device(info: BluetoothServiceInfoBleak) -> BLEDevice:
    if device := getattr(info, "device", None):
        return device
    return BLEDevice(info.address, info.name or info.address, {}, -1, -1, -1)


def _advertisement(info: BluetoothServiceInfoBleak) -> AdvertisementData:
    if adv := getattr(info, "advertisement", None):
        return adv
    return AdvertisementData(
        local_name=info.name,
        manufacturer_data=info.manufacturer_data,
        service_data=info.service_data,
        service_uuids=list(info.service_uuids),
        tx_power=info.tx_power,
        rssi=info.rssi,
        platform_data=(),
    )


def _is_puffco(info: BluetoothServiceInfoBleak) -> bool:
    """True when an advert looks like a Puffco Peak / Proxy."""
    return is_peak_pro_advertisement(_ble_device(info), _advertisement(info))


def _device_label(info: BluetoothServiceInfoBleak) -> str:
    name = info.name or "Puffco"
    if info.rssi is not None:
        return f"{name} ({info.address}) · {info.rssi} dBm"
    return f"{name} ({info.address})"


async def _async_scan_puffco_devices(
    hass: HomeAssistant, *, exclude: set[str]
) -> dict[str, str]:
    """Collect Puffco-looking devices from HA cache and an active scan."""
    found: dict[str, BluetoothServiceInfoBleak] = {}

    def _maybe_add(info: BluetoothServiceInfoBleak) -> None:
        if info.address in exclude:
            return
        if not _is_puffco(info):
            return
        existing = found.get(info.address)
        if existing is None or (info.rssi or -999) > (existing.rssi or -999):
            found[info.address] = info

    for connectable in (True, False):
        for info in async_discovered_service_info(hass, connectable=connectable):
            _maybe_add(info)

    @callback
    def _on_device(
        service_info: BluetoothServiceInfoBleak, _change: BluetoothChange
    ) -> None:
        _maybe_add(service_info)

    unregister = bluetooth.async_register_callback(
        hass,
        _on_device,
        {"connectable": True},
        BluetoothScanningMode.ACTIVE,
    )
    try:
        await asyncio.sleep(SCAN_TIMEOUT_S)
    finally:
        unregister()

    return {
        address: _device_label(info)
        for address, info in sorted(
            found.items(),
            key=lambda item: item[1].rssi if item[1].rssi is not None else -999,
            reverse=True,
        )
    }


class PuffcoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return PuffcoOptionsFlow(config_entry)

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, str] = {}

    def _configured_addresses(self) -> set[str]:
        return {address.upper() for address in self._async_current_ids()}

    def _load_cached_devices(self) -> None:
        self._discovered = {}
        exclude = self._configured_addresses()
        for connectable in (True, False):
            for info in async_discovered_service_info(
                self.hass, connectable=connectable
            ):
                if info.address in exclude or not _is_puffco(info):
                    continue
                self._discovered[info.address] = _device_label(info)

    def _device_picker_schema(self) -> vol.Schema:
        options = dict(self._discovered)
        options[OPTION_SCAN] = "Scan for devices…"
        options[OPTION_MANUAL] = "Enter MAC address manually"
        return vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)})

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> config_entries.ConfigFlowResult:
        """Handle a device discovered by Home Assistant Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        assert self._discovery is not None
        info = self._discovery
        name = info.name or info.address
        if user_input is not None:
            return await self._async_validate_and_create(info.address, name)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == OPTION_MANUAL:
                return await self.async_step_manual()
            if address == OPTION_SCAN:
                return await self.async_step_scan()
            return await self._async_validate_and_create(
                address, self._discovered.get(address, address)
            )

        self._load_cached_devices()
        return self.async_show_form(
            step_id="user",
            data_schema=self._device_picker_schema(),
        )

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Actively scan for Puffco devices."""
        if user_input is not None:
            if not self._discovered:
                return await self.async_step_scan_failed()
            return await self.async_step_user()

        self.context["title_placeholders"] = {"timeout": str(SCAN_TIMEOUT_S)}
        return self.async_show_progress(
            step_id="scan",
            progress_action="scanning",
            progress_task=self._async_run_scan(),
        )

    async def _async_run_scan(self) -> None:
        self._discovered = await _async_scan_puffco_devices(
            self.hass, exclude=self._configured_addresses()
        )

    async def async_step_scan_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            if user_input["action"] == "retry":
                return await self.async_step_scan()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="scan_failed",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): vol.In(
                        {
                            "retry": "Scan again",
                            OPTION_MANUAL: "Enter MAC address manually",
                        }
                    )
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = user_input[CONF_MAC].strip().upper()
            if not MAC_RE.match(mac):
                errors["base"] = "invalid_mac"
            else:
                return await self._async_validate_and_create(mac, f"Puffco {mac}")

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            errors=errors,
        )

    async def _async_validate_and_create(
        self, address: str, fallback_name: str
    ) -> config_entries.ConfigFlowResult:
        mac = address.upper()
        await self.async_set_unique_id(mac, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        try:
            info = await validate_connection(self.hass, mac)
        except CannotConnect:
            if self._discovery is not None:
                return self.async_abort(reason="cannot_connect")
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
                errors={"base": "cannot_connect"},
            )
        return self.async_create_entry(
            title=info.get("device_name") or fallback_name,
            data={CONF_MAC: mac},
            options={
                CONF_SHOW_DIAGNOSTICS: DEFAULT_SHOW_DIAGNOSTICS,
                CONF_BLOCK_START_WHILE_CHARGING: DEFAULT_BLOCK_START_WHILE_CHARGING,
                CONF_FAST_POLL: DEFAULT_FAST_POLL,
                CONF_WAKE_ON_COMMAND: DEFAULT_WAKE_ON_COMMAND,
                CONF_IDLE_DISCONNECT: DEFAULT_IDLE_DISCONNECT,
            },
        )


class PuffcoOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Handle Puffco integration options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SHOW_DIAGNOSTICS,
                    default=options.get(
                        CONF_SHOW_DIAGNOSTICS, DEFAULT_SHOW_DIAGNOSTICS
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_BLOCK_START_WHILE_CHARGING,
                    default=options.get(
                        CONF_BLOCK_START_WHILE_CHARGING,
                        DEFAULT_BLOCK_START_WHILE_CHARGING,
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_FAST_POLL,
                    default=options.get(CONF_FAST_POLL, DEFAULT_FAST_POLL),
                ): cv.boolean,
                vol.Optional(
                    CONF_WAKE_ON_COMMAND,
                    default=options.get(
                        CONF_WAKE_ON_COMMAND, DEFAULT_WAKE_ON_COMMAND
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_IDLE_DISCONNECT,
                    default=options.get(
                        CONF_IDLE_DISCONNECT, DEFAULT_IDLE_DISCONNECT
                    ),
                ): cv.boolean,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class PuffcoFixFlow(config_entries.ConfigFlow):
    """Repair flow when BLE reconnect fails."""

    DOMAIN = DOMAIN

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_confirm(user_input)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="confirm")

        mac = self.data.get("mac", "").upper()
        coordinator = None
        for entry_coordinator in self.hass.data.get(DOMAIN, {}).values():
            if entry_coordinator.mac == mac:
                coordinator = entry_coordinator
                break
        if coordinator is not None:
            with contextlib.suppress(Exception):
                await coordinator.async_reconnect(clear_bond=True)
        ir.async_delete_issue(self.hass, DOMAIN, f"reconnect_{mac}")
        return self.async_create_entry(title="", data={})


async def async_get_fix_flow(hass, issue_id: str, data: dict[str, Any] | None):
    if issue_id.startswith("reconnect_"):
        return PuffcoFixFlow
    return None
