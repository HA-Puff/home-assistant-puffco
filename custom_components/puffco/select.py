"""Select platform for active heat profile."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROFILE_COUNT
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoControllableEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PuffcoActiveProfileSelect(coordinator)])


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
