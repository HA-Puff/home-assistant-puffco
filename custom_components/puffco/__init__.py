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
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = PuffcoDataUpdateCoordinator(hass, entry)
    entry.async_on_unload(coordinator.async_start())

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_apply_entity_registry(hass, entry)
    return True


def _async_apply_entity_registry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Disable diagnostic entities by default unless the user opted in."""
    if entry.options.get(CONF_SHOW_DIAGNOSTICS, DEFAULT_SHOW_DIAGNOSTICS):
        return
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.disabled_by is not None:
            continue
        if any(
            entity.unique_id and entity.unique_id.endswith(suffix)
            for suffix in DIAGNOSTIC_ENTITY_SUFFIXES
        ):
            registry.async_update_entity(
                entity.entity_id,
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
