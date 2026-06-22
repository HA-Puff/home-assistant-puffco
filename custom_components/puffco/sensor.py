"""Sensor platform for Puffco."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ACTIVE_PROFILE,
    ATTR_FIRMWARE,
    ATTR_OPERATING_STATE,
    ATTR_PROTOCOL,
    DOMAIN,
    is_heat_cycle_state,
)
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoPersistentStateEntity
from .helpers import OPERATING_STATE_OPTIONS


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PuffcoTotalDabsSensor(coordinator),
            PuffcoTripDabsSensor(coordinator),
            PuffcoDabsPerDaySensor(coordinator),
            PuffcoHeaterTempSensor(coordinator),
            PuffcoHeatTimeRemainingSensor(coordinator),
            PuffcoHeatCycleTimer(coordinator),
            PuffcoBatterySensor(coordinator),
            PuffcoFirmwareSensor(coordinator),
            PuffcoOperatingStateSensor(coordinator),
        ]
    )


class PuffcoSensorBase(PuffcoPersistentStateEntity, SensorEntity):
    """Base for Puffco sensors."""


class PuffcoTotalDabsSensor(PuffcoSensorBase):
    _attr_translation_key = "total_dabs"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_total_dabs"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data:
            return self.coordinator.data.total_dabs
        return None


class PuffcoTripDabsSensor(PuffcoSensorBase):
    _attr_translation_key = "trip_dabs"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_trip_dabs"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data:
            return self.coordinator.data.trip_dabs
        return None


class PuffcoDabsPerDaySensor(PuffcoSensorBase):
    _attr_translation_key = "dabs_per_day"
    _attr_icon = "mdi:chart-line"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_dabs_per_day"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.dabs_per_day
        return None


class PuffcoHeaterTempSensor(PuffcoSensorBase):
    _attr_translation_key = "heater_temp"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_heater_temp"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.heater_temp_c
        return None


class PuffcoHeatTimeRemainingSensor(PuffcoSensorBase):
    """Countdown while preheating / heating / fading (matches the Puffco app timer)."""

    _attr_translation_key = "heat_time_remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_heat_time_remaining"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data or not is_heat_cycle_state(data.operating_state):
            return None
        if data.state_total_s is None or data.state_elapsed_s is None:
            return None
        return max(0.0, round(data.state_total_s - data.state_elapsed_s))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        attrs = {ATTR_OPERATING_STATE: data.operating_state}
        if data.state_elapsed_s is not None:
            attrs["state_elapsed_seconds"] = round(data.state_elapsed_s)
        if data.state_total_s is not None:
            attrs["state_total_seconds"] = round(data.state_total_s)
        return attrs


class PuffcoHeatCycleTimer(PuffcoSensorBase):
    """Remaining heat-cycle time with finishes_at for timer cards."""

    _attr_translation_key = "heat_cycle_timer"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_heat_cycle_timer"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data or not is_heat_cycle_state(data.operating_state):
            return None
        if data.state_total_s is None or data.state_elapsed_s is None:
            return None
        return max(0.0, round(data.state_total_s - data.state_elapsed_s))

    @property
    def extra_state_attributes(self) -> dict:
        remaining = self.native_value
        if remaining is None:
            return {}
        finishes = dt_util.utcnow() + timedelta(seconds=remaining)
        return {
            "finishes_at": dt_util.as_local(finishes).isoformat(),
            "active": True,
        }


class PuffcoBatterySensor(PuffcoSensorBase):
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_battery"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data:
            return self.coordinator.data.battery_percent
        return None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        attrs = {"charge_state": data.battery_charge_state}
        if data.charge_eta_seconds is not None:
            attrs["charge_eta_minutes"] = round(data.charge_eta_seconds / 60)
        return attrs


class PuffcoFirmwareSensor(PuffcoSensorBase):
    _attr_translation_key = "firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_firmware"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.firmware
        return None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        return {
            ATTR_PROTOCOL: self.coordinator.data.protocol,
            ATTR_FIRMWARE: self.coordinator.data.firmware,
            ATTR_ACTIVE_PROFILE: self.coordinator.data.active_profile + 1,
        }


class PuffcoOperatingStateSensor(PuffcoSensorBase):
    _attr_translation_key = "operating_state"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(OPERATING_STATE_OPTIONS)
    _attr_icon = "mdi:state-machine"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_operating_state"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.operating_state
        return None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        return {ATTR_OPERATING_STATE: self.coordinator.data.operating_state}
