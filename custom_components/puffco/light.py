"""Light platform for Puffco lantern / mood lighting."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import color as color_util

from .const import DOMAIN, LANTERN_SYNC_GUARD, LANTERN_WRITE_DEBOUNCE, PROFILE_COUNT
from .coordinator import PuffcoDataUpdateCoordinator
from .entity import PuffcoControllableEntity, PuffcoPersistentStateEntity
from puffco_ble.encoding import clamp_brightness, clamp_byte
from puffco_ble.lantern_effects import (
    DEFAULT_LANTERN_EFFECT,
    LANTERN_EFFECT_BY_NAME,
    LANTERN_EFFECT_NAMES,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_BRIGHTNESS = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PuffcoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[LightEntity] = [PuffcoLanternLight(coordinator)]
    entities.extend(
        PuffcoProfileColorLight(coordinator, profile)
        for profile in range(PROFILE_COUNT)
    )
    async_add_entities(entities)


class PuffcoLanternLight(PuffcoControllableEntity, LightEntity):
    """Logo / lantern light with RGB color wheel, brightness, and effects."""

    _attr_translation_key = "lantern"
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(LANTERN_EFFECT_NAMES)
    _attr_icon = "mdi:lava-lamp"
    _attr_brightness = DEFAULT_BRIGHTNESS

    def __init__(self, coordinator: PuffcoDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_lantern"
        self._rgb = (255, 255, 255)
        self._effect = DEFAULT_LANTERN_EFFECT
        self._debounce_generation = 0
        self._debounce_task: asyncio.Task | None = None
        self._lantern_sync_guard_until = 0.0

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data:
            return self.coordinator.data.lantern_on
        return None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self._rgb

    @property
    def effect(self) -> str | None:
        return self._effect

    @staticmethod
    def _parse_lantern_color(
        data: bytes | bytearray | None,
    ) -> tuple[tuple[int, int, int], str] | None:
        if not data or len(data) < 8:
            return None
        from puffco_ble.constants import LanternAnimation

        raw = bytes(data)
        for preset in LanternAnimation.ALL:
            if raw == preset:
                for effect in LANTERN_EFFECT_BY_NAME.values():
                    if effect.preset == preset:
                        return ((raw[0], raw[1], raw[2]), effect.name)
        mode = raw[4]
        effect_name = DEFAULT_LANTERN_EFFECT
        for effect in LANTERN_EFFECT_BY_NAME.values():
            if effect.mode is not None and int(effect.mode) == mode:
                effect_name = effect.name
                break
        return ((raw[0], raw[1], raw[2]), effect_name)

    @staticmethod
    def _clamp_rgb(rgb: tuple) -> tuple[int, int, int]:
        return (clamp_byte(rgb[0]), clamp_byte(rgb[1]), clamp_byte(rgb[2]))

    def _apply_turn_on_kwargs(self, kwargs: dict) -> None:
        if (rgb := kwargs.get("rgb_color")) is not None:
            self._rgb = self._clamp_rgb(rgb)
        elif (rgbw := kwargs.get("rgbw_color")) is not None:
            self._rgb = self._clamp_rgb(color_util.rgbw_to_rgb(*rgbw))
        elif (hs := kwargs.get("hs_color")) is not None:
            self._rgb = self._clamp_rgb(
                color_util.color_hs_to_RGB(hs[0], hs[1])
            )
        elif (xy := kwargs.get("xy_color")) is not None:
            self._rgb = self._clamp_rgb(
                color_util.color_xy_to_RGB(xy[0], xy[1])
            )

        if (effect := kwargs.get("effect")) is not None:
            self._effect = effect

        if (brightness := kwargs.get("brightness")) is not None:
            clamped = clamp_brightness(brightness)
            if clamped is not None:
                self._attr_brightness = clamped

    async def _commit_lantern(self) -> None:
        effect = LANTERN_EFFECT_BY_NAME.get(self._effect)
        uses_color = effect is None or effect.uses_color
        r, g, b = self._rgb
        if not uses_color:
            r, g, b = 255, 255, 255

        async def _write(client):
            await client.set_lantern(
                r=clamp_byte(r),
                g=clamp_byte(g),
                b=clamp_byte(b),
                effect_name=self._effect,
                brightness=clamp_brightness(self.brightness),
                enabled=True,
            )

        await self.coordinator.async_write(_write, refresh=False)
        self._lantern_sync_guard_until = time.monotonic() + LANTERN_SYNC_GUARD
        self.async_write_ha_state()

    async def _debounced_commit(self, generation: int) -> None:
        try:
            await asyncio.sleep(LANTERN_WRITE_DEBOUNCE)
            if generation != self._debounce_generation:
                return
            await self._commit_lantern()
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.exception("Lantern color update failed")

    def _lantern_state_is_local(self) -> bool:
        """True while UI/BLE lantern state should not be overwritten by poll."""
        if self._debounce_task is not None and not self._debounce_task.done():
            return True
        return time.monotonic() < self._lantern_sync_guard_until

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._lantern_state_is_local():
            if self.coordinator.data:
                clamped = clamp_brightness(self.coordinator.data.lantern_brightness)
                if clamped is not None:
                    self._attr_brightness = clamped
            client = (
                self.coordinator._client.bleak  # noqa: SLF001
                if self.coordinator._client
                else None
            )
            if client and client.lantern_color:
                parsed = self._parse_lantern_color(client.lantern_color)
                if parsed:
                    self._rgb, self._effect = parsed
        super()._handle_coordinator_update()

    async def _cancel_debounce_task(self) -> None:
        if self._debounce_task is not None:
            self._debounce_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._debounce_task

    async def async_turn_on(self, **kwargs) -> None:
        self._apply_turn_on_kwargs(kwargs)

        # Off→on and effect changes commit immediately; only debounce color drags.
        if not self.is_on or kwargs.get("effect") is not None:
            await self._cancel_debounce_task()
            await self._commit_lantern()
            return

        self._debounce_generation += 1
        generation = self._debounce_generation
        await self._cancel_debounce_task()
        self.async_write_ha_state()
        self._debounce_task = self.hass.async_create_task(
            self._debounced_commit(generation)
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self._cancel_debounce_task()
        await self.coordinator.async_write(
            lambda client: client.set_lantern_enabled(False),
            refresh=False,
        )


class PuffcoProfileColorLight(PuffcoPersistentStateEntity, LightEntity):
    """Profile accent color — visible on Controls; writes require an awake Peak."""

    _attr_translation_key = "profile_color"
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB
    _attr_icon = "mdi:palette"

    def __init__(
        self, coordinator: PuffcoDataUpdateCoordinator, profile_index: int
    ) -> None:
        super().__init__(coordinator)
        self._profile_index = profile_index
        self._attr_unique_id = (
            f"{coordinator.mac}_profile_{profile_index + 1}_color"
        )
        self._attr_translation_placeholders = {
            "profile": str(profile_index + 1)
        }

    @property
    def is_on(self) -> bool:
        return self.rgb_color is not None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        data = self.coordinator.data
        if (
            data
            and data.profile_colors_rgb
            and len(data.profile_colors_rgb) > self._profile_index
        ):
            return data.profile_colors_rgb[self._profile_index]
        return None

    async def async_turn_on(self, **kwargs) -> None:
        if not self.coordinator.commands_reachable:
            raise HomeAssistantError(
                "Peak is asleep or out of range — wake it first."
            )
        rgb = kwargs.get("rgb_color") or self.rgb_color or (255, 255, 255)
        profile = self._profile_index

        async def _write(client):
            await client.set_profile_color(
                profile, clamp_byte(rgb[0]), clamp_byte(rgb[1]), clamp_byte(rgb[2])
            )

        await self.coordinator.async_write(_write, profile_index=profile)
