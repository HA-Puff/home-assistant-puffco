"""Text platform for Puffco profile names."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PROFILE_COUNT
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoControllableEntity, PuffcoProfileDevice
from puffco_ble.constants import DEVICE_NAME_MAX_LENGTH


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PuffcoDeviceNameText(coordinator),
            *[
                PuffcoProfileNameText(coordinator, profile)
                for profile in range(PROFILE_COUNT)
            ],
        ]
    )


class PuffcoDeviceNameText(PuffcoControllableEntity, TextEntity):
    """Bluetooth name stored on the Peak."""

    _attr_translation_key = "device_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = DEVICE_NAME_MAX_LENGTH
    _attr_icon = "mdi:rename-box"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_device_name"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.device_name or None

    async def async_set_value(self, value: str) -> None:
        name = value.strip()

        async def _write(client):
            await client.set_device_name(name)

        await self.coordinator.async_write(_write, updates={"device_name": name})


class PuffcoProfileNameText(
    PuffcoProfileDevice, PuffcoControllableEntity, TextEntity
):
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
