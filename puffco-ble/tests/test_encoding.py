"""Encoding and packing tests."""

import struct

import pytest

from puffco_ble.constants import DeviceCommands, LanternMode
from puffco_ble.encoding import (
    firmware_int_to_string,
    pack_mode_command,
    pack_static_lantern_color,
    parse_rgb_hex,
)


def test_profile_temp_287c():
    assert struct.pack("<f", 287.0).hex() == "00808f43"


def test_mode_command_heat_cycle_start():
    assert pack_mode_command(DeviceCommands.HEAT_CYCLE_START) == bytes.fromhex(
        "0000e040"
    )


def test_static_red_lantern():
    data = pack_static_lantern_color(0xFF, 0x00, 0x00, LanternMode.STATIC)
    assert list(data) == [0xFF, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00]


def test_parse_rgb_hex():
    assert parse_rgb_hex("#FF0000") == (255, 0, 0)
    assert parse_rgb_hex("00FF00") == (0, 255, 0)


def test_firmware_int_to_string():
    # Firmware revision encoding uses custom alphabet; spot-check non-zero
    assert firmware_int_to_string(0) == "X*"
    rev = firmware_int_to_string(24)
    assert isinstance(rev, str)
    assert len(rev) >= 1


def test_parse_rgb_invalid():
    with pytest.raises(ValueError):
        parse_rgb_hex("FF")
