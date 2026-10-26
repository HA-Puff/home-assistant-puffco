"""Select platform for active heat profile."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROFILE_COUNT
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoControllableEntity, PuffcoProfileDevice
from puffco_ble.constants import VAPOR_LEVELS
from puffco_ble.encoding import (
    ready_mode_option,
    ready_mode_value,
    vapor_level_key,
    vapor_level_value,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = [
        PuffcoActiveProfileSelect(coordinator),
        PuffcoReadyModeSelect(coordinator),
    ]
    entities.extend(
        PuffcoProfileIntensitySelect(coordinator, profile)
        for profile in range(PROFILE_COUNT)
    )
    async_add_entities(entities)


class PuffcoActiveProfileSelect(PuffcoControllableEntity, SelectEntity):
    _attr_translation_key = "active_profile"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:fire-circle"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_active_profile"
        self._attr_options = [str(i) for i in range(1, PROFILE_COUNT + 1)]

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data:
            return str(self.coordinator.data.active_profile + 1)
        return None

    async def async_select_option(self, option: str) -> None:
        profile = int(option) - 1

        async def _write(client):
            await client.bleak.change_profile(profile, current=True)

        await self.coordinator.async_write(_write)


class PuffcoReadyModeSelect(PuffcoControllableEntity, SelectEntity):
    """Heat a profile when the Peak is lifted off the Power Dock."""

    _attr_translation_key = "ready_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:dock-top"
    _attr_options = ["off", "1", "2", "3", "4"]

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_ready_mode"

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        return ready_mode_option(data.ready_mode_cycle)

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data
        if data is not None and data.protocol != "lorax":
            raise HomeAssistantError("Ready mode requires Lorax firmware.")
        cycle = ready_mode_value(option)

        async def _write(client):
            await client.set_ready_mode_cycle(cycle)

        await self.coordinator.async_write(
            _write, updates={"ready_mode_cycle": cycle}
        )


class PuffcoProfileIntensitySelect(
    PuffcoProfileDevice, PuffcoControllableEntity, SelectEntity
):
    """Per-profile vapor / cloud size. Four fixed steps from the Puffco app."""

    _attr_translation_key = "profile_intensity"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:cloud-outline"
    _attr_options = [key for key, _level in VAPOR_LEVELS]

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator)
        self._profile_index = profile_index
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_intensity"
        )
        self._attr_translation_placeholders = {
            "profile": str(profile_index + 1)
        }

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if (
            data
            and data.profile_intensity
            and len(data.profile_intensity) > self._profile_index
        ):
            return vapor_level_key(data.profile_intensity[self._profile_index])
        return None

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data
        if data is not None and data.protocol != "lorax":
            raise HomeAssistantError(
                "Intensity is available on Lorax firmware (AC or newer)."
            )
        level = vapor_level_value(option)
        profile = self._profile_index

        async def _write(client):
            await client.set_profile_intensity(profile, level)

        await self.coordinator.async_write(_write, profile_index=profile)
