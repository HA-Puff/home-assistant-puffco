"""Binary encoding and decoding for Puffco BLE payloads."""

from __future__ import annotations

import math
import struct
from typing import Iterable

from puffco_ble.constants import (
    DeviceCommands,
    LanternMode,
    REVISION_CHARS,
)


def parse_float(data: bytes | bytearray) -> float:
    """Unpack little-endian float from 4-byte characteristic value."""
    return struct.unpack("<f", bytes(data[:4]))[0]


def finite_float(data: bytes | bytearray | None) -> float | None:
    """Parse float32; None when missing, nan, or inf."""
    if not data or len(data) < 4:
        return None
    raw = parse_float(data)
    if not math.isfinite(raw):
        return None
    return raw


def safe_int_from_float(value: float, *, default: int = 0) -> int:
    """int() that survives nan/inf from bad BLE reads or HA payloads."""
    if not math.isfinite(value):
        return default
    return int(value)


def safe_int_from_float_bytes(data: bytes | bytearray | None, *, default: int = 0) -> int:
    parsed = finite_float(data) if data is not None else None
    if parsed is None:
        return default
    return safe_int_from_float(parsed, default=default)


def parse_uint32(data: bytes | bytearray) -> int:
    return struct.unpack("<I", bytes(data[:4]))[0]


def finite_round(value: float | None, ndigits: int = 0) -> float | None:
    """round() that returns None for nan/inf instead of propagating bad BLE data."""
    if value is None or not math.isfinite(value):
        return None
    return round(value, ndigits)


def clamp_byte(value: object, *, default: int = 255) -> int:
    """Coerce a color/brightness channel to 0–255 (guards inf/nan from HA)."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0, min(255, int(number)))


def clamp_brightness(value: object | None, *, default: int = 255) -> int | None:
    if value is None:
        return None
    return clamp_byte(value, default=default)


def parse_lorax_short_number(
    data: bytes | bytearray | str | None,
    *,
    max_reasonable: float | None = None,
) -> float | None:
    """Parse a Lorax READ_SHORT payload (ASCII decimal, uint32, or float32)."""
    if data is None:
        return None
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    else:
        raw = bytes(data)
        if not raw:
            return None
        text = raw.decode("utf-8", errors="ignore").strip("\x00").strip()
        if text and text.replace(".", "", 1).replace("-", "", 1).isdigit():
            try:
                value = float(text)
            except ValueError:
                value = None
        else:
            value = None
        if value is None and len(raw) >= 4:
            as_u32 = float(parse_uint32(raw))
            as_f = parse_float(raw)
            if math.isnan(as_f):
                value = as_u32
            elif as_u32 > 10_000_000 and 0 <= as_f <= (max_reasonable or 1_000_000_000):
                value = as_f
            elif 0 <= as_u32 <= (max_reasonable or 1_000_000_000):
                value = as_u32
            else:
                value = as_f if not math.isnan(as_f) else as_u32
        elif value is None:
            value = float(int.from_bytes(raw, "little"))
    if max_reasonable is not None and (value < 0 or value > max_reasonable):
        return None
    if not math.isfinite(value):
        return None
    return value


def pack_float(value: float) -> bytes:
    return struct.pack("<f", value)


def pack_mode_command(command: DeviceCommands | int) -> bytes:
    """Flat protocol encodes mode commands as float32."""
    return struct.pack("<f", float(int(command)))


def pack_lorax_mode_command(command: DeviceCommands | int) -> bytes:
    return int(command).to_bytes(1, "little")


def pack_static_lantern_color(
    r: int, g: int, b: int, mode: LanternMode = LanternMode.STATIC
) -> bytearray:
    mode_byte = clamp_byte(int(mode), default=int(LanternMode.STATIC))
    return bytearray(
        [
            clamp_byte(r),
            clamp_byte(g),
            clamp_byte(b),
            0,
            mode_byte,
            0,
            0,
            0,
        ]
    )


def pack_lantern_on(enabled: bool, lorax: bool = False) -> bytearray:
    if lorax:
        return bytearray([int(enabled)])
    return bytearray([int(enabled), 0, 0, 0])


def parse_rgb_hex(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected 6-digit hex color, got {hex_color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def firmware_int_to_string(rev: int) -> str:
    """Convert Lorax firmware integer to revision string (e.g. AW)."""
    if rev <= 0:
        return "X*"
    i = rev - 1
    rev_string = ""
    while i >= 0:
        rev_string = REVISION_CHARS[i % len(REVISION_CHARS)] + rev_string
        i = math.floor(i / len(REVISION_CHARS)) - 1
    return rev_string


def meets_minimum_firmware(current: str, minimum: str) -> bool:
    """Compare Puffco firmware revision strings."""

    def to_index(rev: str) -> int:
        if not rev:
            return -1
        value = 0
        for char in rev:
            value = value * len(REVISION_CHARS) + REVISION_CHARS.index(char) + 1
        return value

    return to_index(current) >= to_index(minimum)


def celsius_to_fahrenheit(celsius: float) -> float:
    return (celsius * 9 / 5) + 32


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def operating_state_name(state_id: int) -> str:
    from puffco_ble.constants import OperatingState

    try:
        return OperatingState(state_id).name.lower()
    except ValueError:
        return f"unknown_{state_id}"


def battery_charge_state_name(state_id: int) -> str:
    from puffco_ble.constants import BatteryChargeState

    try:
        return BatteryChargeState(state_id).name.lower()
    except ValueError:
        return f"unknown_{state_id}"


def is_battery_charging(state_id: int) -> bool:
    from puffco_ble.constants import BatteryChargeState

    return state_id in (BatteryChargeState.BULK, BatteryChargeState.TOPUP)


def is_battery_on_dock(state_id: int) -> bool:
    from puffco_ble.constants import BatteryChargeState

    return state_id != BatteryChargeState.DISCONNECTED


def chamber_type_name(type_id: int) -> str:
    from puffco_ble.constants import ChamberType

    try:
        return ChamberType(type_id).name.lower()
    except ValueError:
        return f"unknown_{type_id}"


def parse_profile_color(data: bytes | bytearray) -> tuple[int, int, int]:
    if not data or len(data) < 3:
        return (0, 0, 0)
    return int(data[0]), int(data[1]), int(data[2])
