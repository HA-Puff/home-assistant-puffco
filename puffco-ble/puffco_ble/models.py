"""Device state models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class PuffcoData:
    total_dabs: int
    trip_dabs: int
    dabs_per_day: float
    heater_temp_c: float | None
    profile_temp_c: float
    profile_temps_c: list[float]
    profile_times_s: list[float]
    active_profile: int
    operating_state: str
    battery_percent: int
    lantern_on: bool
    firmware: str
    protocol: Literal["flat", "lorax"]
    state_elapsed_s: float | None = None
    state_total_s: float | None = None
    device_name: str = ""
    model_name: str = ""
    stealth_mode: bool = False
    battery_charging: bool = False
    battery_charge_state: str = "disconnected"
    charge_eta_seconds: float | None = None
    profile_names: list[str] | None = None
    profile_colors_rgb: list[tuple[int, int, int]] | None = None
    profile_boost_temps_c: list[float] | None = None
    profile_boost_times_s: list[float] | None = None
    lantern_brightness: int = 255
    led_brightness: tuple[int, int, int, int] = (255, 255, 255, 255)
    chamber_type: str = "unknown"
    approx_dabs_remaining: int | None = None
    device_birthday: str = ""
    uptime_seconds: float | None = None
    total_heat_cycle_time_s: float | None = None
    serial_number: str = ""
