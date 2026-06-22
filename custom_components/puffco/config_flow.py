"""Config flow for Puffco integration."""

from __future__ import annotations

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
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_MAC
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_BLOCK_START_WHILE_CHARGING,
    CONF_FAST_POLL,
    CONF_SHOW_DIAGNOSTICS,
    DEFAULT_BLOCK_START_WHILE_CHARGING,
    DEFAULT_FAST_POLL,
    DEFAULT_SHOW_DIAGNOSTICS,
    DOMAIN,
)
from .coordinator import CannotConnect, validate_connection
from puffco_ble.constants import (
    LORAX_SERVICE_UUID,
    PEAK_PRO_MAC_PREFIXES,
    SERVICE_UUID,
)

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

_PUFFCO_SERVICE_UUIDS = {SERVICE_UUID.lower(), LORAX_SERVICE_UUID.lower()}


def _is_puffco(info: BluetoothServiceInfoBleak) -> bool:
    if any(
        info.address.upper().startswith(p.upper()) for p in PEAK_PRO_MAC_PREFIXES
    ):
        return True
    if _PUFFCO_SERVICE_UUIDS & {u.lower() for u in info.service_uuids}:
        return True
    name = (info.name or "").lower()
    return "puffco" in name or "peak" in name


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
            if address == "__manual__":
                return await self.async_step_manual()
            return await self._async_validate_and_create(
                address, self._discovered.get(address, address)
            )

        current = self._async_current_ids()
        self._discovered = {}
        for info in async_discovered_service_info(self.hass):
            if info.address in current:
                continue
            if _is_puffco(info):
                self._discovered[info.address] = f"{info.name or 'Puffco'} ({info.address})"

        if not self._discovered:
            return await self.async_step_manual()

        options = dict(self._discovered)
        options["__manual__"] = "Enter MAC address manually"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
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
