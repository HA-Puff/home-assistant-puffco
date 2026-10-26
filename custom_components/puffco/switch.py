"""Switch platform for Puffco stealth mode."""

from __future__ import annotations

import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STEALTH_SYNC_GUARD
from puffco_ble.constants import (
    FULL_BATTERY_SOC,
    LOW_BATTERY_WARN_OFF,
    LOW_BATTERY_WARN_ON,
    PRESERVATION_BATTERY_SOC,
)
from puffco_ble.encoding import (
    battery_preservation_enabled,
    low_battery_warn_enabled,
)
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoEntity, PuffcoControllableEntity, PuffcoSessionControllableEntity

async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PuffcoHeatSessionSwitch(coordinator),
            PuffcoStealthSwitch(coordinator),
            PuffcoBatteryPreservationSwitch(coordinator),
            PuffcoLowBatteryIndicatorSwitch(coordinator),
        ]
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


class _LoraxConfigSwitch(PuffcoControllableEntity, PuffcoSwitchBase):
    """Device setting that exists on Lorax firmware only."""

    _attr_entity_category = EntityCategory.CONFIG

    def _require_lorax(self) -> None:
        data = self.coordinator.data
        if data is not None and data.protocol != "lorax":
            raise HomeAssistantError("This setting requires Lorax firmware.")


class PuffcoBatteryPreservationSwitch(_LoraxConfigSwitch):
    """Cap charging at 80%."""

    _attr_translation_key = "battery_preservation"
    _attr_icon = "mdi:battery-heart"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_battery_preservation"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        return battery_preservation_enabled(data.max_battery_soc)

    async def async_turn_on(self, **kwargs) -> None:
        self._require_lorax()

        async def _write(client):
            await client.set_max_battery_soc(PRESERVATION_BATTERY_SOC)

        await self.coordinator.async_write(
            _write, updates={"max_battery_soc": PRESERVATION_BATTERY_SOC}
        )

    async def async_turn_off(self, **kwargs) -> None:
        self._require_lorax()

        async def _write(client):
            await client.set_max_battery_soc(FULL_BATTERY_SOC)

        await self.coordinator.async_write(
            _write, updates={"max_battery_soc": FULL_BATTERY_SOC}
        )


class PuffcoLowBatteryIndicatorSwitch(_LoraxConfigSwitch):
    """Light the device when the battery is low."""

    _attr_translation_key = "low_battery_indicator"
    _attr_icon = "mdi:battery-alert"

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_low_battery_indicator"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        return low_battery_warn_enabled(data.low_battery_warn)

    async def async_turn_on(self, **kwargs) -> None:
        self._require_lorax()

        async def _write(client):
            await client.set_low_battery_warn(LOW_BATTERY_WARN_ON)

        await self.coordinator.async_write(
            _write, updates={"low_battery_warn": LOW_BATTERY_WARN_ON}
        )

    async def async_turn_off(self, **kwargs) -> None:
        self._require_lorax()

        async def _write(client):
            await client.set_low_battery_warn(LOW_BATTERY_WARN_OFF)

        await self.coordinator.async_write(
            _write, updates={"low_battery_warn": LOW_BATTERY_WARN_OFF}
        )
