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
from .helpers import is_on_dock
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoPersistentStateEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PuffcoAwakeBinarySensor(coordinator),
            PuffcoAdvertisingBinarySensor(coordinator),
            PuffcoConnectedBinarySensor(coordinator),
            PuffcoChargingBinarySensor(coordinator),
        ]
    )


class PuffcoBinarySensorBase(PuffcoPersistentStateEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class PuffcoAwakeBinarySensor(PuffcoPersistentStateEntity, BinarySensorEntity):
    """On when the Peak is awake (advertising or connected to Home Assistant)."""

    _attr_translation_key = "awake"
    _attr_icon = "mdi:sleep-off"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_awake"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is not None or self.coordinator.is_awake:
            return self.coordinator.is_awake
        return None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            **self._connectivity_attributes(),
            "advertising": self.coordinator.is_advertising,
        }


class PuffcoAdvertisingBinarySensor(PuffcoBinarySensorBase):
    """On when the Peak is advertising (awake and in range)."""

    _attr_translation_key = "advertising"
    _attr_icon = "mdi:bluetooth"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_advertising"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None and self.coordinator.last_seen is None:
            return None
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
        if self.coordinator.data is None and self.coordinator.last_seen is None:
            return None
        return self.coordinator.ble_connected


class PuffcoChargingBinarySensor(PuffcoPersistentStateEntity, BinarySensorEntity):
    """On while the Peak is on the charging dock (including full)."""

    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_charging"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            if self.coordinator.last_seen is None:
                return None
            return False
        return is_on_dock(self.coordinator.data.battery_charge_state)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return self._connectivity_attributes()
        data = self.coordinator.data
        return {
            **self._connectivity_attributes(),
            "actively_charging": data.battery_charging,
            "charge_state": data.battery_charge_state,
        }
