"""Number platform for Puffco profile temperature and duration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    PROFILE_COUNT,
    PROFILE_TIME_CEILING_S,
    PROFILE_TIME_FLOOR_S,
    TEMPERATURE_CEILING_C,
    TEMPERATURE_FLOOR_C,
)
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for profile in range(PROFILE_COUNT):
        entities.append(PuffcoProfileTempNumber(coordinator, profile))
        entities.append(PuffcoProfileTimeNumber(coordinator, profile))
    async_add_entities(entities)


class PuffcoProfileSettingNumber(PuffcoEntity, NumberEntity):
    """Shared base for per-profile settings shown under device configuration."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.AUTO

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator)
        self._profile_index = profile_index
        self._attr_translation_placeholders = {
            "profile": str(profile_index + 1)
        }


class PuffcoProfileTempNumber(PuffcoProfileSettingNumber):
    _attr_translation_key = "profile_temp"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = TEMPERATURE_FLOOR_C
    _attr_native_max_value = TEMPERATURE_CEILING_C
    _attr_native_step = 1
    _attr_icon = "mdi:thermometer"

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator, profile_index)
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_temp"
        )

    @property
    def native_value(self) -> float | None:
        if (
            self.coordinator.data
            and len(self.coordinator.data.profile_temps_c) > self._profile_index
        ):
            return self.coordinator.data.profile_temps_c[self._profile_index]
        return None

    async def async_set_native_value(self, value: float) -> None:
        profile = self._profile_index

        async def _write(client):
            await client.set_profile_temperature(profile, value)

        await self.coordinator.async_write(_write, profile_index=profile)


class PuffcoProfileTimeNumber(PuffcoProfileSettingNumber):
    _attr_translation_key = "profile_time"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = PROFILE_TIME_FLOOR_S
    _attr_native_max_value = PROFILE_TIME_CEILING_S
    _attr_native_step = 1
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator, profile_index)
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_time"
        )

    @property
    def native_value(self) -> float | None:
        if (
            self.coordinator.data
            and len(self.coordinator.data.profile_times_s) > self._profile_index
        ):
            return round(self.coordinator.data.profile_times_s[self._profile_index])
        return None

    async def async_set_native_value(self, value: float) -> None:
        profile = self._profile_index

        async def _write(client):
            await client.set_profile_time(profile, value)

        await self.coordinator.async_write(_write, profile_index=profile)
