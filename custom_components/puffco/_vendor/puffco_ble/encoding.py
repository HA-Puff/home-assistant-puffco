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


def parse_uint32(data: bytes | bytearray) -> int:
    return struct.unpack("<I", bytes(data[:4]))[0]


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
    return bytearray([r & 0xFF, g & 0xFF, b & 0xFF, 0, int(mode), 0, 0, 0])


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
