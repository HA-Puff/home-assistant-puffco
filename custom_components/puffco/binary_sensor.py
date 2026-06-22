"""Binary sensors for Puffco connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity, PuffcoPersistentStateEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PuffcoAdvertisingBinarySensor(coordinator),
            PuffcoConnectedBinarySensor(coordinator),
            PuffcoChargingBinarySensor(coordinator),
        ]
    )


class PuffcoBinarySensorBase(PuffcoEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class PuffcoAdvertisingBinarySensor(PuffcoBinarySensorBase):
    """On when the Peak is advertising (awake and in range)."""

    _attr_translation_key = "advertising"
    _attr_icon = "mdi:bluetooth"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_advertising"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.is_advertising


class PuffcoConnectedBinarySensor(PuffcoPersistentStateEntity, BinarySensorEntity):
    """On when Home Assistant has an active BLE session to the Peak."""

    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_connected"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is not None:
            return self.coordinator.ble_connected
        return None


class PuffcoChargingBinarySensor(PuffcoPersistentStateEntity, BinarySensorEntity):
    """On while the Peak is actively charging on the dock."""

    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_charging"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is not None:
            return self.coordinator.data.battery_charging
        return None
