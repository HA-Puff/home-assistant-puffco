"""Number platform for Puffco profile temperature and duration."""

from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BOOST_TEMP_CEILING_C,
    BOOST_TEMP_FLOOR_C,
    BOOST_TIME_CEILING_S,
    BOOST_TIME_FLOOR_S,
    DOMAIN,
    LED_BRIGHTNESS_MAX,
    LED_BRIGHTNESS_MIN,
    PROFILE_COUNT,
    PROFILE_TIME_CEILING_S,
    PROFILE_TIME_FLOOR_S,
    TEMPERATURE_CEILING_C,
    TEMPERATURE_FLOOR_C,
)
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoControllableEntity
from puffco_ble.encoding import clamp_brightness, finite_round


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
        entities.append(PuffcoProfileBoostTempNumber(coordinator, profile))
        entities.append(PuffcoProfileBoostTimeNumber(coordinator, profile))
    entities.extend(
        [
            PuffcoLanternBrightnessNumber(coordinator),
            PuffcoLedBrightnessRingNumber(coordinator),
            PuffcoLedBrightnessGlassNumber(coordinator),
            PuffcoLedBrightnessMainNumber(coordinator),
            PuffcoLedBrightnessBatteryNumber(coordinator),
        ]
    )
    async_add_entities(entities)


class PuffcoProfileSettingNumber(PuffcoControllableEntity, NumberEntity):
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
            value = self.coordinator.data.profile_temps_c[self._profile_index]
            return value if math.isfinite(value) else None
        return None

    async def async_set_native_value(self, value: float) -> None:
        if not math.isfinite(value):
            return
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
            return finite_round(
                self.coordinator.data.profile_times_s[self._profile_index]
            )
        return None

    async def async_set_native_value(self, value: float) -> None:
        if not math.isfinite(value):
            return
        profile = self._profile_index

        async def _write(client):
            await client.set_profile_time(profile, value)

        await self.coordinator.async_write(_write, profile_index=profile)


class PuffcoProfileBoostTempNumber(PuffcoProfileSettingNumber):
    _attr_translation_key = "profile_boost_temp"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = BOOST_TEMP_FLOOR_C
    _attr_native_max_value = BOOST_TEMP_CEILING_C
    _attr_native_step = 1
    _attr_icon = "mdi:fire-alert"

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator, profile_index)
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_boost_temp"
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if (
            data
            and data.profile_boost_temps_c
            and len(data.profile_boost_temps_c) > self._profile_index
        ):
            return finite_round(data.profile_boost_temps_c[self._profile_index])
        return None

    async def async_set_native_value(self, value: float) -> None:
        if not math.isfinite(value):
            return
        profile = self._profile_index

        async def _write(client):
            await client.set_boost_temperature(profile, value)

        await self.coordinator.async_write(_write, profile_index=profile)


class PuffcoProfileBoostTimeNumber(PuffcoProfileSettingNumber):
    _attr_translation_key = "profile_boost_time"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = BOOST_TIME_FLOOR_S
    _attr_native_max_value = BOOST_TIME_CEILING_S
    _attr_native_step = 1
    _attr_icon = "mdi:timer-plus"

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator, profile_index)
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_boost_time"
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if (
            data
            and data.profile_boost_times_s
            and len(data.profile_boost_times_s) > self._profile_index
        ):
            return finite_round(data.profile_boost_times_s[self._profile_index])
        return None

    async def async_set_native_value(self, value: float) -> None:
        if not math.isfinite(value):
            return
        profile = self._profile_index

        async def _write(client):
            await client.set_boost_time(profile, value)

        await self.coordinator.async_write(_write, profile_index=profile)


class PuffcoLanternBrightnessNumber(PuffcoControllableEntity, NumberEntity):
    _attr_translation_key = "lantern_brightness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.AUTO
    _attr_native_min_value = LED_BRIGHTNESS_MIN
    _attr_native_max_value = LED_BRIGHTNESS_MAX
    _attr_native_step = 1
    _attr_icon = "mdi:brightness-6"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_lantern_brightness"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return clamp_brightness(self.coordinator.data.lantern_brightness)
        return None

    async def async_set_native_value(self, value: float) -> None:
        brightness = clamp_brightness(value)
        if brightness is None:
            return
        await self.coordinator.async_write(
            lambda client: client.set_lantern_brightness(brightness)
        )


class _PuffcoLedSegmentBrightness(PuffcoControllableEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.AUTO
    _attr_native_min_value = LED_BRIGHTNESS_MIN
    _attr_native_max_value = LED_BRIGHTNESS_MAX
    _attr_native_step = 1
    _segment_index: int

    def _segments(self) -> tuple[int, int, int, int]:
        if self.coordinator.data:
            return self.coordinator.data.led_brightness
        return (255, 255, 255, 255)

    @property
    def native_value(self) -> float | None:
        segments = self._segments()
        return segments[self._segment_index]

    async def async_set_native_value(self, value: float) -> None:
        if not math.isfinite(value):
            return
        segments = list(self._segments())
        segments[self._segment_index] = clamp_brightness(value) or LED_BRIGHTNESS_MIN

        async def _write(client):
            await client.set_led_brightness(*segments)

        await self.coordinator.async_write(_write)


class PuffcoLedBrightnessRingNumber(_PuffcoLedSegmentBrightness):
    _attr_translation_key = "led_brightness_ring"
    _attr_icon = "mdi:brightness-5"
    _segment_index = 0

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_led_brightness_ring"


class PuffcoLedBrightnessGlassNumber(_PuffcoLedSegmentBrightness):
    _attr_translation_key = "led_brightness_glass"
    _attr_icon = "mdi:brightness-5"
    _segment_index = 1

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_led_brightness_glass"


class PuffcoLedBrightnessMainNumber(_PuffcoLedSegmentBrightness):
    _attr_translation_key = "led_brightness_main"
    _attr_icon = "mdi:brightness-5"
    _segment_index = 2

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_led_brightness_main"


class PuffcoLedBrightnessBatteryNumber(_PuffcoLedSegmentBrightness):
    _attr_translation_key = "led_brightness_battery"
    _attr_icon = "mdi:brightness-5"
    _segment_index = 3

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_led_brightness_battery"
