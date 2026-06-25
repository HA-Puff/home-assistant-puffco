"""Puffco Home Assistant integration."""

from __future__ import annotations

import logging
import os
import sys

# The puffco_ble library is vendored under ``_vendor/`` inside this component.
_VENDORED_DIR = os.path.join(os.path.dirname(__file__), "_vendor")
if _VENDORED_DIR not in sys.path:
    sys.path.insert(0, _VENDORED_DIR)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_SHOW_DIAGNOSTICS,
    DEFAULT_SHOW_DIAGNOSTICS,
    DIAGNOSTIC_ENTITY_SUFFIXES,
    DOMAIN,
)
from .coordinator import PuffcoDataUpdateCoordinator
from .service_handlers import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.EVENT,
    Platform.TEXT,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = PuffcoDataUpdateCoordinator(hass, entry)
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_apply_entity_registry(hass, entry)
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-apply diagnostic entity visibility when integration options change."""
    show = entry.options.get(CONF_SHOW_DIAGNOSTICS, DEFAULT_SHOW_DIAGNOSTICS)
    _async_apply_entity_registry(hass, entry)
    coordinator: PuffcoDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None:
        coordinator.async_update_listeners()
        if show:
            coordinator.async_request_full_refresh()


def _async_apply_entity_registry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show or hide diagnostic entities based on the integration option."""
    show = entry.options.get(CONF_SHOW_DIAGNOSTICS, DEFAULT_SHOW_DIAGNOSTICS)
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not entity.unique_id:
            continue
        if not any(entity.unique_id.endswith(suffix) for suffix in DIAGNOSTIC_ENTITY_SUFFIXES):
            continue
        if show:
            if entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                registry.async_update_entity(entity.entity_id, disabled_by=None)
        elif entity.disabled_by is None:
            registry.async_update_entity(
                entity.entity_id,
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
