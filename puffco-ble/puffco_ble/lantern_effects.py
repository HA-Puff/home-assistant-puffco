"""Lantern effects: logo-light colors and precompiled base-ring moods."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Literal

from puffco_ble.constants import LanternAnimation, LanternMode
from puffco_ble.encoding import clamp_byte, pack_static_lantern_color
from puffco_ble.lantern_presets import EXCLUSIVE_LANTERN_PRESETS

EffectKind = Literal["rgb_mode", "preset", "blob"]

# LED API 2 firmware (the Peak answers 8-byte colors) cannot take a compiled
# mood on /p/app/ltrn/colr. The app uploads the colors and offsets to a user
# array, then points the lantern at it with an 8-byte table color. The lantern
# alternates between arrays 5 and 6 so the running pattern is never rewritten.
LANTERN_MOOD_SLOTS = (5, 6)
# Heat profile N (0-3) owns user array 1 + N.
PROFILE_MOOD_SLOT_BASE = 1
_NVM_USER_ARRAY_OFFSET = 8
_MOOD_COLOR_COUNT = 32
_TABLE_MARKER = 1


@dataclass(frozen=True, slots=True)
class LanternMood:
    """Mood parameters for LED API 2 user arrays."""

    colors: bytes
    offsets: bytes
    bright: int
    speed: int
    anim: int
    pl_num: int
    pl_denom: int
    color_len: int

    def table_color(self, slot: int) -> bytearray:
        index = _NVM_USER_ARRAY_OFFSET + slot
        return bytearray(
            (
                self.bright,
                self.speed,
                self.anim,
                _TABLE_MARKER,
                self.pl_num,
                self.pl_denom,
                (index << 4) | index,
                self.color_len if self.color_len < _MOOD_COLOR_COUNT else 0,
            )
        )

    def matches_table(self, raw: bytes) -> bool:
        if len(raw) != 8 or raw[3] != _TABLE_MARKER:
            return False
        own = self.table_color(LANTERN_MOOD_SLOTS[0])
        return all(raw[i] == own[i] for i in (0, 1, 2, 4, 5, 7))


def table_color_slot(raw: bytes | bytearray | None) -> int | None:
    """User array index a table lantern color points at."""
    if not raw or len(raw) != 8 or raw[3] != _TABLE_MARKER:
        return None
    return (raw[6] & 0x0F) - _NVM_USER_ARRAY_OFFSET


def _cbor(data: bytes, i: int) -> tuple[Any, int]:
    head = data[i]
    i += 1
    major, info = head >> 5, head & 0x1F
    if major == 7 and info in (26, 27):
        size = 4 if info == 26 else 8
        return struct.unpack(">f" if size == 4 else ">d", data[i : i + size])[0], i + size
    if info < 24:
        value = info
    else:
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        value = int.from_bytes(data[i : i + size], "big")
        i += size
    if major == 0:
        return value, i
    if major == 1:
        return -1 - value, i
    if major == 2:
        return bytes(data[i : i + value]), i + value
    if major == 3:
        return data[i : i + value].decode(), i + value
    if major == 4:
        items = []
        for _ in range(value):
            item, i = _cbor(data, i)
            items.append(item)
        return items, i
    if major == 5:
        mapping = {}
        for _ in range(value):
            key, i = _cbor(data, i)
            mapping[key], i = _cbor(data, i)
        return mapping, i
    if major == 6:
        return _cbor(data, i)
    return {20: False, 21: True, 22: None}.get(value, value), i


def mood_from_blob(blob: bytes) -> LanternMood:
    """LED API 2 mood from a compiled pikaled2 lantern payload."""
    param = _cbor(blob, 0)[0]["lamp"]["param"]
    rgb = bytes(param.get("color") or b"")[: _MOOD_COLOR_COUNT * 3]
    colors = bytearray()
    for i in range(_MOOD_COLOR_COUNT):
        colors += rgb[i * 3 : i * 3 + 3].ljust(3, b"\x00") + b"\x00"
    offsets = b"".join(struct.pack("<I", int(v) & 0xFFFFFFFF) for v in param.get("offset") or ())
    return LanternMood(
        colors=bytes(colors),
        offsets=offsets,
        bright=int(param.get("bright", 255)),
        speed=int(param.get("speed", 255)),
        anim=int(param.get("anim", 0)),
        pl_num=int(param.get("plNum", 0)),
        pl_denom=int(param.get("plDenom", 0)),
        color_len=int(param.get("colorLen", _MOOD_COLOR_COUNT)),
    )


@dataclass(frozen=True, slots=True)
class LanternEffect:
    """One selectable lantern effect."""

    name: str
    kind: EffectKind
    mode: LanternMode | None = None
    preset: bytes | None = None
    uses_color: bool = True
    swatch: tuple[int, int, int] | None = None
    mood: LanternMood | None = None


# Order matches the Puffco app UI (steady + luma modes + preset animations).
# Pulsing / Rotating / Disco are the same logo-light mode bytes as Breathing /
# Circling Slow / Solid. They take the color picker: RGB replaces bytes 0-2.
LANTERN_EFFECTS: tuple[LanternEffect, ...] = (
    LanternEffect("Solid", "rgb_mode", LanternMode.STATIC),
    LanternEffect("Breathing", "rgb_mode", LanternMode.BREATHING),
    LanternEffect("Rising", "rgb_mode", LanternMode.RISING),
    LanternEffect("Circling", "rgb_mode", LanternMode.CIRCLING),
    LanternEffect("Circling Slow", "rgb_mode", LanternMode.CIRCLING_SLOW),
    LanternEffect("Pulsing", "rgb_mode", LanternMode.BREATHING),
    LanternEffect("Rotating", "rgb_mode", LanternMode.CIRCLING_SLOW),
    LanternEffect("Disco", "rgb_mode", LanternMode.STATIC),
    *(
        LanternEffect(
            name,
            "blob",
            preset=blob,
            uses_color=False,
            swatch=swatch,
            mood=mood_from_blob(blob),
        )
        for name, swatch, blob in EXCLUSIVE_LANTERN_PRESETS
    ),
)

LANTERN_EFFECT_NAMES: tuple[str, ...] = tuple(e.name for e in LANTERN_EFFECTS)
LANTERN_EFFECT_BY_NAME: dict[str, LanternEffect] = {e.name: e for e in LANTERN_EFFECTS}
MOOD_EFFECT_NAMES: tuple[str, ...] = tuple(e.name for e in LANTERN_EFFECTS if e.mood is not None)
_BLOB_BY_BYTES: dict[bytes, LanternEffect] = {
    bytes(effect.preset): effect
    for effect in LANTERN_EFFECTS
    if effect.kind == "blob" and effect.preset is not None
}

DEFAULT_LANTERN_EFFECT = "Solid"

# Historical yellow blobs. Same mode bytes as Breathing / Circling Slow / Solid.
_PRESET_BYTES_TO_NAME: dict[bytes, str] = {
    bytes(LanternAnimation.PULSING): "Pulsing",
    bytes(LanternAnimation.ROTATING): "Rotating",
    bytes(LanternAnimation.DISCO_MODE): "Disco",
}


def effect_mode_byte(effect: LanternEffect) -> int | None:
    """Logo-light animation byte (rgbtApi2 index 4)."""
    if effect.kind == "blob":
        return None
    if effect.mode is not None:
        return int(effect.mode)
    if effect.preset is not None and len(effect.preset) >= 5:
        return int(effect.preset[4])
    return None


def pack_lantern_effect(name: str, r: int, g: int, b: int) -> bytearray:
    """8-byte rgbtApi2 payload. Mode byte stays; RGB fills the first three bytes."""
    effect = LANTERN_EFFECT_BY_NAME.get(name)
    if effect is None:
        effect = LANTERN_EFFECT_BY_NAME[DEFAULT_LANTERN_EFFECT]
    r = clamp_byte(r)
    g = clamp_byte(g)
    b = clamp_byte(b)
    if effect.kind == "blob" and effect.preset is not None:
        return bytearray(effect.preset)
    if effect.kind == "preset" and effect.preset is not None:
        payload = bytearray(effect.preset)
        payload[0] = r
        payload[1] = g
        payload[2] = b
        return payload
    mode = effect.mode if effect.mode is not None else LanternMode.STATIC
    return pack_static_lantern_color(r, g, b, mode=mode)


def parse_lantern_color(
    data: bytes | bytearray | None,
    *,
    selected: str | None = None,
) -> tuple[tuple[int, int, int], str] | None:
    """RGB and effect name from an 8-byte lantern color.

    The effect is identified from the mode byte, so a recolored Pulsing,
    Rotating, or Disco (RGB other than the old yellow preset) still matches
    ``selected`` when that effect uses the same mode byte.
    """
    if not data:
        return None
    raw = bytes(data)
    blob = _BLOB_BY_BYTES.get(raw)
    if blob is not None:
        return (blob.swatch or (raw[0], raw[1], raw[2]), blob.name)
    if len(raw) != 8:
        return None
    if raw[3] == _TABLE_MARKER:
        moods = [e for e in LANTERN_EFFECTS if e.mood is not None and e.mood.matches_table(raw)]
        if selected:
            for effect in moods:
                if effect.name == selected:
                    return (effect.swatch or (0, 0, 0), effect.name)
        if moods:
            return (moods[0].swatch or (0, 0, 0), moods[0].name)
        return None
    rgb = (raw[0], raw[1], raw[2])
    mode = raw[4]

    # Unchanged yellow blobs still name Pulsing / Rotating / Disco.
    preset_name = _PRESET_BYTES_TO_NAME.get(raw)
    if preset_name is not None:
        return (rgb, preset_name)

    # Recolored payload: keep the effect already selected when its mode matches.
    if selected:
        current = LANTERN_EFFECT_BY_NAME.get(selected)
        if current is not None and effect_mode_byte(current) == mode:
            return (rgb, current.name)

    for effect in LANTERN_EFFECTS:
        if effect_mode_byte(effect) == mode:
            return (rgb, effect.name)
    return (rgb, DEFAULT_LANTERN_EFFECT)
