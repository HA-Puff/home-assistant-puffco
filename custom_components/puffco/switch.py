"""Switch platform for Puffco stealth mode."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PuffcoStealthSwitch(coordinator)])


class PuffcoStealthSwitch(PuffcoEntity, SwitchEntity):
    _attr_translation_key = "stealth_mode"
    _attr_icon = "mdi:eye-off"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_stealth_mode"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data:
            return self.coordinator.data.stealth_mode
        return None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_write(
            lambda client: client.bleak.set_stealth_mode(True)
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_write(
            lambda client: client.bleak.set_stealth_mode(False)
        )
