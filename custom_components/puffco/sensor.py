"""Sensor platform for Puffco."""

from __future__ import annotations

import math
from datetime import date, timedelta

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
from .helpers import OPERATING_STATE_OPTIONS, CHAMBER_TYPE_OPTIONS


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        PuffcoTotalDabsSensor(coordinator),
        PuffcoTripDabsSensor(coordinator),
        PuffcoDabsPerDaySensor(coordinator),
        PuffcoHeaterTempSensor(coordinator),
        PuffcoHeatTimeRemainingSensor(coordinator),
        PuffcoHeatCycleTimer(coordinator),
        PuffcoBatterySensor(coordinator),
        PuffcoFirmwareSensor(coordinator),
        PuffcoOperatingStateSensor(coordinator),
        PuffcoChamberTypeSensor(coordinator),
        PuffcoApproxDabsRemainingSensor(coordinator),
        PuffcoDeviceBirthdaySensor(coordinator),
        PuffcoUptimeSensor(coordinator),
        PuffcoTotalHeatTimeSensor(coordinator),
    ]
    async_add_entities(entities)


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
            value = self.coordinator.data.dabs_per_day
            return value if math.isfinite(value) else None
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
            temp = self.coordinator.data.heater_temp_c
            return temp if temp is not None and math.isfinite(temp) else None
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
        return self.coordinator.heat_seconds_remaining()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        attrs = {
            **self._connectivity_attributes(),
            ATTR_OPERATING_STATE: data.operating_state,
            "active": is_heat_cycle_state(data.operating_state)
            or self.coordinator.session_timer_active,
            "local_timer": self.coordinator.session_timer_active,
        }
        if data.state_elapsed_s is not None and math.isfinite(data.state_elapsed_s):
            attrs["state_elapsed_seconds"] = round(data.state_elapsed_s)
        if data.state_total_s is not None and math.isfinite(data.state_total_s):
            attrs["state_total_seconds"] = round(data.state_total_s)
        if self.coordinator.session_finishes_at is not None:
            attrs["finishes_at"] = dt_util.as_local(
                self.coordinator.session_finishes_at
            ).isoformat()
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
        return self.coordinator.heat_seconds_remaining()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        remaining = self.native_value
        active = (
            is_heat_cycle_state(data.operating_state)
            or self.coordinator.session_timer_active
        )
        if not active:
            return {**self._connectivity_attributes(), "active": False}
        if remaining is None or not math.isfinite(remaining):
            return {
                **self._connectivity_attributes(),
                "active": True,
                "local_timer": self.coordinator.session_timer_active,
            }
        finishes = self.coordinator.session_finishes_at
        if finishes is None:
            finishes = dt_util.utcnow() + timedelta(seconds=remaining)
        return {
            **self._connectivity_attributes(),
            "finishes_at": dt_util.as_local(finishes).isoformat(),
            "active": True,
            "local_timer": self.coordinator.session_timer_active,
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
        if data.charge_eta_seconds is not None and math.isfinite(data.charge_eta_seconds):
            attrs["charge_eta_minutes"] = round(data.charge_eta_seconds / 60)
        return {**self._connectivity_attributes(), **attrs}


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
            **self._connectivity_attributes(),
            ATTR_PROTOCOL: self.coordinator.data.protocol,
            ATTR_FIRMWARE: self.coordinator.data.firmware,
            ATTR_ACTIVE_PROFILE: self.coordinator.data.active_profile + 1,
            "serial_number": self.coordinator.data.serial_number or None,
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
        return {
            **self._connectivity_attributes(),
            ATTR_OPERATING_STATE: self.coordinator.data.operating_state,
        }


class PuffcoChamberTypeSensor(PuffcoSensorBase):
    _attr_translation_key = "chamber_type"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CHAMBER_TYPE_OPTIONS)
    _attr_icon = "mdi:cube-outline"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_chamber_type"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.chamber_type
        return None


class PuffcoApproxDabsRemainingSensor(PuffcoSensorBase):
    _attr_translation_key = "approx_dabs_remaining"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-heart"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_approx_dabs_remaining"

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data:
            return self.coordinator.data.approx_dabs_remaining
        return None


class PuffcoDeviceBirthdaySensor(PuffcoSensorBase):
    _attr_translation_key = "device_birthday"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:cake-variant"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_device_birthday"

    @property
    def native_value(self) -> date | None:
        if not self.coordinator.data or not self.coordinator.data.device_birthday:
            return None
        raw = self.coordinator.data.device_birthday
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None


class PuffcoUptimeSensor(PuffcoSensorBase):
    _attr_translation_key = "uptime"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_uptime"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.uptime_seconds
        return None


class PuffcoTotalHeatTimeSensor(PuffcoSensorBase):
    _attr_translation_key = "total_heat_time"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:fire-clock"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_total_heat_time"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return self.coordinator.data.total_heat_cycle_time_s
        return None
