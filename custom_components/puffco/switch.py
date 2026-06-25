"""Switch platform for Puffco stealth mode."""

from __future__ import annotations

import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STEALTH_SYNC_GUARD
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity, PuffcoControllableEntity, PuffcoSessionControllableEntity

async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [PuffcoHeatSessionSwitch(coordinator), PuffcoStealthSwitch(coordinator)]
    )


class PuffcoSwitchBase(PuffcoEntity, SwitchEntity):
    """Switch entities with coordinator device info."""


class PuffcoHeatSessionSwitch(PuffcoSessionControllableEntity, PuffcoSwitchBase):
    """Start / abort a heat session — clearer than climate heat/off."""

    _attr_translation_key = "heat_session"
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_heat_session"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.in_heat_session:
            return True
        if self.coordinator.data:
            return False
        return None

    async def async_turn_on(self, **kwargs) -> None:
        if not self.coordinator.in_heat_session:
            await self.coordinator.async_start_session()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_abort_session()


class PuffcoStealthSwitch(PuffcoControllableEntity, PuffcoSwitchBase):
    _attr_translation_key = "stealth_mode"
    _attr_icon = "mdi:eye-off"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_stealth_mode"
        self._local_stealth: bool | None = None
        self._stealth_guard_until = 0.0

    @property
    def is_on(self) -> bool | None:
        if (
            self._local_stealth is not None
            and time.monotonic() < self._stealth_guard_until
        ):
            return self._local_stealth
        if self.coordinator.data:
            return self.coordinator.data.stealth_mode
        return None

    async def async_turn_on(self, **kwargs) -> None:
        self._local_stealth = True
        self._stealth_guard_until = time.monotonic() + STEALTH_SYNC_GUARD
        await self.coordinator.async_write(
            lambda client: client.bleak.set_stealth_mode(True),
            stealth_mode=True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        self._local_stealth = False
        self._stealth_guard_until = time.monotonic() + STEALTH_SYNC_GUARD
        await self.coordinator.async_write(
            lambda client: client.bleak.set_stealth_mode(False),
            stealth_mode=False,
        )
