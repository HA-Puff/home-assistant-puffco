"""Button platform for Puffco session control."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity, PuffcoSessionControllableEntity

_LOGGER = logging.getLogger(__name__)


class PuffcoButtonBase(PuffcoEntity, ButtonEntity):
    """Buttons register with coordinator device info."""


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PuffcoReconnectButton(coordinator),
            PuffcoStartSessionButton(coordinator),
            PuffcoAbortSessionButton(coordinator),
            PuffcoBoostSessionButton(coordinator),
        ]
    )


class PuffcoReconnectButton(PuffcoButtonBase):
    """Manual reconnect; stays available when the Peak is offline."""

    _attr_translation_key = "reconnect"
    _attr_icon = "mdi:bluetooth-connect"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_reconnect"

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_reconnect()
        except HomeAssistantError as err:
            if "not visible" in str(err).lower():
                raise
            _LOGGER.info("Standard reconnect failed, retrying with bond clear: %s", err)
            await self.coordinator.async_reconnect(clear_bond=True)


class PuffcoSessionButtonBase(PuffcoSessionControllableEntity, PuffcoButtonBase):
    """Session buttons with correct coordinator + button MRO."""


class PuffcoStartSessionButton(PuffcoSessionButtonBase):
    _attr_translation_key = "start_session"
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_start_session"

    async def async_press(self) -> None:
        await self.coordinator.async_start_session()


class PuffcoAbortSessionButton(PuffcoSessionButtonBase):
    _attr_translation_key = "abort_session"
    _attr_icon = "mdi:stop"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_abort_session"

    async def async_press(self) -> None:
        await self.coordinator.async_abort_session()


class PuffcoBoostSessionButton(PuffcoSessionButtonBase):
    _attr_translation_key = "boost_session"
    _attr_icon = "mdi:rocket-launch"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_boost_session"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.in_heat_session

    async def async_press(self) -> None:
        await self.coordinator.async_boost_session()
