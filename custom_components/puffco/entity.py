"""Base entity for Puffco using the active Bluetooth coordinator."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .coordinator import PuffcoDataUpdateCoordinator


class PuffcoEntity(PassiveBluetoothCoordinatorEntity[PuffcoDataUpdateCoordinator]):
    """Common base for Puffco entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        """Push cached state when an entity is enabled (e.g. diagnostic toggles)."""
        await super().async_added_to_hass()
        if self.coordinator.data is not None:
            self.async_write_ha_state()

    def _connectivity_attributes(self) -> dict:
        """Extra attributes for sleepy-device context (merge into subclass attrs)."""
        attrs: dict = {}
        if self.coordinator.data is not None and not self.coordinator.ble_connected:
            attrs["data_stale"] = True
        if self.coordinator.last_seen is not None:
            attrs["last_seen"] = dt_util.as_local(
                self.coordinator.last_seen
            ).isoformat()
        attrs["awake"] = self.coordinator.is_awake
        attrs["ble_connected"] = self.coordinator.ble_connected
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class PuffcoPersistentStateEntity(PuffcoEntity):
    """Read-only entities that keep the last reading when the Peak sleeps."""

    @property
    def available(self) -> bool:
        if self.coordinator.data is not None:
            return True
        return super().available

    @property
    def extra_state_attributes(self) -> dict:
        return self._connectivity_attributes()


class PuffcoControllableEntity(PuffcoEntity):
    """Writable entities — unavailable while the Peak is asleep and out of range."""

    @property
    def available(self) -> bool:
        return self.coordinator.commands_reachable


class PuffcoSessionControllableEntity(PuffcoEntity):
    """Session controls stay available during a local heat timer even if BLE drops."""

    @property
    def available(self) -> bool:
        return (
            self.coordinator.commands_reachable or self.coordinator.in_heat_session
        )
