"""Climate platform — optional heater UI (profile + temp). Prefer switch/buttons for on/off."""

from __future__ import annotations

import math

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TEMPERATURE_CEILING_C, TEMPERATURE_FLOOR_C, is_heat_cycle_state
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity, PuffcoSessionControllableEntity
from .helpers import (
    PRESET_MODES,
    preset_mode_for_profile,
    profile_index_from_preset,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PuffcoHeaterClimate(coordinator)])


class PuffcoClimateBase(PuffcoEntity, ClimateEntity):
    """Climate entities with coordinator device info."""


class PuffcoHeaterClimate(PuffcoSessionControllableEntity, PuffcoClimateBase):
    """Peak chamber heater — good for temp/profile; use switch.*_heat_session for on/off."""

    _attr_translation_key = "heater"
    _attr_icon = "mdi:fire"
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = list(PRESET_MODES)
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = TEMPERATURE_FLOOR_C
    _attr_max_temp = TEMPERATURE_CEILING_C
    _attr_target_temperature_step = 1.0
    _attr_precision = 1.0

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_heater"

    @property
    def current_temperature(self) -> float | None:
        if self.coordinator.data:
            temp = self.coordinator.data.heater_temp_c
            if temp is not None and math.isfinite(temp):
                return temp
            profile_temp = self.coordinator.data.profile_temp_c
            if math.isfinite(profile_temp):
                return profile_temp
        return None

    @property
    def target_temperature(self) -> float | None:
        if self.coordinator.data:
            temp = self.coordinator.data.profile_temp_c
            return temp if math.isfinite(temp) else None
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        if self.coordinator.in_heat_session:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self.coordinator.data:
            return HVACAction.OFF
        state = self.coordinator.data.operating_state
        if state == "heat_cycle_preheat":
            return getattr(HVACAction, "PREHEATING", HVACAction.HEATING)
        if state == "heat_cycle_active":
            return HVACAction.HEATING
        if state == "heat_cycle_fade":
            return HVACAction.COOLING
        if is_heat_cycle_state(state):
            return HVACAction.HEATING
        if self.coordinator.session_timer_active:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if self.coordinator.data:
            return preset_mode_for_profile(self.coordinator.data.active_profile)
        return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT:
            await self.async_turn_on()
        elif hvac_mode in (HVACMode.OFF, HVACMode.HEAT_COOL):
            await self.async_turn_off()

    async def async_set_temperature(self, **kwargs) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None or self.coordinator.data is None:
            return
        if not math.isfinite(float(temp)):
            return
        profile = self.coordinator.data.active_profile

        async def _write(client):
            await client.set_profile_temperature(profile, float(temp))

        await self.coordinator.async_write(_write, profile_index=profile)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        try:
            profile = profile_index_from_preset(preset_mode)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_set_profile(profile + 1)

    async def async_turn_on(self, **kwargs) -> None:
        if self.coordinator.in_heat_session:
            return
        await self.coordinator.async_start_session()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_abort_session()
