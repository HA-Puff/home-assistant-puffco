"""Shared helpers for the Puffco integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, PROFILE_COUNT
from puffco_ble.constants import OperatingState
from puffco_ble.encoding import operating_state_name

OPERATING_STATE_OPTIONS: tuple[str, ...] = tuple(
    operating_state_name(int(state)) for state in OperatingState
)

PRESET_MODES: tuple[str, ...] = tuple(f"Profile {i}" for i in range(1, PROFILE_COUNT + 1))


def preset_mode_for_profile(profile_index: int) -> str:
    return f"Profile {profile_index + 1}"


def profile_index_from_preset(preset: str) -> int:
    if preset.startswith("Profile "):
        return max(0, min(PROFILE_COUNT - 1, int(preset.split()[-1]) - 1))
    raise ValueError(f"Unknown preset {preset!r}")


def get_coordinator(hass: HomeAssistant, entry_id: str):
    return hass.data[DOMAIN][entry_id]


def get_coordinator_for_device(hass: HomeAssistant, device_id: str):
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None, None
    for identifier in device.identifiers:
        if identifier[0] == DOMAIN:
            mac = identifier[1]
            break
    else:
        return None, None
    for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
        if coordinator.mac == mac:
            return coordinator, entry_id
    return None, None


def get_coordinator_from_service_call(hass: HomeAssistant, call) -> tuple:
    """Resolve coordinator from a service call target."""
    target = call.target
    device_ids = target.device_id if target else None
    entity_ids = target.entity_id if target else None

    if entity_ids:
        entity_reg = er.async_get(hass)
        for entity_id in entity_ids:
            if (entry := entity_reg.async_get(entity_id)) is not None:
                return get_coordinator(hass, entry.config_entry_id), entry.config_entry_id
    if device_ids:
        for device_id in device_ids:
            coordinator, entry_id = get_coordinator_for_device(hass, device_id)
            if coordinator is not None:
                return coordinator, entry_id
    return None, None
