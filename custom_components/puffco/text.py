"""Text platform for Puffco profile names."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
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
    async_add_entities(
        [PuffcoProfileNameText(coordinator, profile) for profile in range(PROFILE_COUNT)]
    )


class PuffcoProfileNameText(PuffcoControllableEntity, TextEntity):
    _attr_translation_key = "profile_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 32
    _attr_icon = "mdi:rename"

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator)
        self._profile_index = profile_index
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_name"
        )
        self._attr_translation_placeholders = {
            "profile": str(profile_index + 1)
        }

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data and data.profile_names and len(data.profile_names) > self._profile_index:
            return data.profile_names[self._profile_index] or ""
        return None

    async def async_set_value(self, value: str) -> None:
        profile = self._profile_index

        async def _write(client):
            await client.set_profile_name(profile, value.strip())

        await self.coordinator.async_write(_write, profile_index=profile)
