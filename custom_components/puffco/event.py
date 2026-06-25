"""Event platform for Puffco session lifecycle and heat-cycle phases."""

from __future__ import annotations

from typing import Callable

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_OPERATING_STATE,
    DOMAIN,
    SESSION_EVENT_TYPES,
    is_heat_cycle_state,
)
from .helpers import is_on_dock
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoPersistentStateEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PuffcoSessionEventEntity(coordinator)])


class PuffcoSessionEventEntity(PuffcoPersistentStateEntity, EventEntity):
    """Fires on session start/finish and each heat-cycle phase from BLE operating state."""

    _attr_translation_key = "session"
    _attr_event_types = list(SESSION_EVENT_TYPES)
    _attr_icon = "mdi:fire-alert"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_session"
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.coordinator.async_register_session_listener(
            self._on_session_event
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _on_session_event(self, event_type: str, data: dict) -> None:
        self._trigger_event(event_type, data)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        attrs = self._connectivity_attributes()
        if not data:
            return attrs
        return {
            **attrs,
            ATTR_OPERATING_STATE: data.operating_state,
            "in_heat_session": self.coordinator.in_heat_session,
            "in_heat_cycle": is_heat_cycle_state(data.operating_state),
            "on_dock": is_on_dock(data.battery_charge_state),
        }
