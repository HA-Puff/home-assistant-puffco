"""Encoding and packing tests."""

import struct

import pytest

from puffco_ble.constants import DeviceCommands, LanternMode
from puffco_ble.encoding import (
    firmware_int_to_string,
    pack_mode_command,
    pack_static_lantern_color,
    parse_rgb_hex,
    battery_preservation_enabled,
    low_battery_warn_enabled,
    ready_mode_option,
    ready_mode_value,
    vapor_level_key,
    vapor_level_value,
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


def test_vapor_levels_round_trip():
    assert vapor_level_key(0.0) == "smooth"
    assert vapor_level_key(0.5) == "bold"
    assert vapor_level_key(1.0) == "intense"
    assert vapor_level_key(1.5) == "extreme"
    assert vapor_level_key(None) is None
    assert vapor_level_value("intense") == 1.0


def test_ready_mode_and_battery_settings():
    assert ready_mode_option(-1) == "off"
    assert ready_mode_option(0) == "1"
    assert ready_mode_option(3) == "4"
    assert ready_mode_value("off") == -1
    assert ready_mode_value("2") == 1
    assert battery_preservation_enabled(80) is True
    assert battery_preservation_enabled(100) is False
    assert low_battery_warn_enabled(10) is True
    assert low_battery_warn_enabled(0) is False


def test_parse_rgb_hex():
    assert parse_rgb_hex("#FF0000") == (255, 0, 0)
    assert parse_rgb_hex("00FF00") == (0, 255, 0)


def test_firmware_int_to_string():
    # Firmware revision encoding uses custom alphabet; spot-check non-zero
    assert firmware_int_to_string(0) == "X*"
    rev = firmware_int_to_string(24)
    assert isinstance(rev, str)
    assert len(rev) >= 1


def test_clamp_byte_rejects_inf():
    from puffco_ble.encoding import clamp_byte

    assert clamp_byte(float("inf")) == 255
    assert clamp_byte(float("nan"), default=0) == 0
    assert clamp_byte(300) == 255
    assert clamp_byte(-5) == 0


def test_safe_int_from_float_rejects_inf():
    import struct

    from puffco_ble.encoding import finite_float, safe_int_from_float, safe_int_from_float_bytes

    assert safe_int_from_float(float("inf")) == 0
    assert safe_int_from_float(float("inf"), default=7) == 7
    inf_bytes = struct.pack("<f", float("inf"))
    assert finite_float(inf_bytes) is None
    assert safe_int_from_float_bytes(inf_bytes) == 0
    assert safe_int_from_float_bytes(struct.pack("<f", 42.0)) == 42


def test_finite_round_rejects_inf():
    from puffco_ble.encoding import finite_round

    assert finite_round(float("inf")) is None
    assert finite_round(42.7) == 43.0
    assert finite_round(42.4) == 42.0


def test_parse_rgb_invalid():
    with pytest.raises(ValueError):
        parse_rgb_hex("FF")


def test_proxy_fixed_point_round_trip():
    from puffco_ble.encoding import chamber_type_name, peak_write_to_proxy, proxy_read_to_peak

    temp = struct.pack("<f", 287.0)
    proxy = peak_write_to_proxy("/u/app/hc/2/temp", temp)
    assert struct.unpack("<i", proxy)[0] == 2870
    assert proxy_read_to_peak("/u/app/hc/2/temp", proxy) == temp

    time_s = struct.pack("<f", 30.0)
    proxy_time = peak_write_to_proxy("/u/app/hc/0/time", time_s)
    assert struct.unpack("<i", proxy_time)[0] == 6000
    assert proxy_read_to_peak("/u/app/hc/0/time", proxy_time) == time_s

    brightness = peak_write_to_proxy("/u/app/ui/lbrt", bytes([10, 20, 30, 40]))
    assert struct.unpack("<i", brightness)[0] == 40 * 256
    assert list(proxy_read_to_peak("/u/app/ui/lbrt", brightness)) == [40, 40, 40, 40]

    dabs = struct.pack("<I", 1234)
    assert struct.unpack("<f", proxy_read_to_peak("/p/app/odom/0/nc", dabs))[0] == 1234.0

    color = bytes([255, 0, 0, 0, 1, 0, 0, 0])
    assert peak_write_to_proxy("/p/app/ltrn/colr", color) == color
    assert proxy_read_to_peak("/p/app/ltrn/colr", color) == color

    assert chamber_type_name(5) == "proxy"
    assert chamber_type_name(4) == "xl"
