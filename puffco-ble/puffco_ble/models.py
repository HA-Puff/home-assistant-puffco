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
    state_elapsed_s: float | None = None
    state_total_s: float | None = None
    battery_percent: int
    lantern_on: bool
    firmware: str
    protocol: Literal["flat", "lorax"]
    device_name: str = ""
    model_name: str = ""
    stealth_mode: bool = False
    battery_charging: bool = False
    battery_charge_state: str = "disconnected"
    charge_eta_seconds: float | None = None
