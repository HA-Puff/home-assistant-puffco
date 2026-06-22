"""Lantern / logo light effects (API2 rgbtApi2, 8 bytes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from puffco_ble.constants import LanternAnimation, LanternMode

EffectKind = Literal["rgb_mode", "preset"]


@dataclass(frozen=True, slots=True)
class LanternEffect:
    """One selectable lantern effect."""

    name: str
    kind: EffectKind
    mode: LanternMode | None = None
    preset: bytes | None = None
    uses_color: bool = True


# Order matches the Puffco app UI (steady + luma modes + preset animations).
LANTERN_EFFECTS: tuple[LanternEffect, ...] = (
    LanternEffect("Solid", "rgb_mode", LanternMode.STATIC),
    LanternEffect("Breathing", "rgb_mode", LanternMode.BREATHING),
    LanternEffect("Rising", "rgb_mode", LanternMode.RISING),
    LanternEffect("Circling", "rgb_mode", LanternMode.CIRCLING),
    LanternEffect("Circling Slow", "rgb_mode", LanternMode.CIRCLING_SLOW),
    LanternEffect("Pulsing", "preset", preset=bytes(LanternAnimation.PULSING), uses_color=False),
    LanternEffect("Rotating", "preset", preset=bytes(LanternAnimation.ROTATING), uses_color=False),
    LanternEffect("Disco", "preset", preset=bytes(LanternAnimation.DISCO_MODE), uses_color=False),
)

LANTERN_EFFECT_NAMES: tuple[str, ...] = tuple(e.name for e in LANTERN_EFFECTS)
LANTERN_EFFECT_BY_NAME: dict[str, LanternEffect] = {e.name: e for e in LANTERN_EFFECTS}

DEFAULT_LANTERN_EFFECT = "Solid"
