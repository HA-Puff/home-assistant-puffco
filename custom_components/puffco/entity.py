"""Base entity for Puffco using the active Bluetooth coordinator."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.core import callback

from .coordinator import PuffcoDataUpdateCoordinator


class PuffcoEntity(PassiveBluetoothCoordinatorEntity[PuffcoDataUpdateCoordinator]):
    """Common base: availability follows advertisements; refresh on poll."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class PuffcoPersistentStateEntity(PuffcoEntity):
    """Read-only entities that keep the last reading when the Peak sleeps.

    Control entities (buttons, lights, etc.) should stay on PuffcoEntity so HA
    marks them unavailable when the BLE link is down.
    """

    @property
    def available(self) -> bool:
        if self.coordinator.data is not None:
            return True
        return super().available
