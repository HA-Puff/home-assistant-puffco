# Deploying Puffco to Home Assistant

## Install

Copy the entire `custom_components/puffco/` folder:

```
/config/custom_components/puffco/
```

The BLE library is vendored at `custom_components/puffco/_vendor/puffco_ble/` — no `pip install` on the HA host.

**Restart Home Assistant** (Settings → System → Restart). Reload is not enough for new platforms or entity changes.

## Add the device

1. Pairing mode for **first setup only**: hold power until the blue light bar glows
2. **Settings → Devices & Services → Add Integration → Puffco**
3. Select discovered device or enter MAC manually
4. **Close the Puffco phone app** — only one BLE client at a time

## Entity reference

Entity IDs: `{domain}.peak_pro_{suffix}_{name}` (MAC-based suffix).

| Entity | Purpose |
|--------|---------|
| `climate.*_heater` | Temp + profile presets (optional dashboard card) |
| `switch.*_heat_session` | **Best for start/stop** — on = heat, off = abort |
| `sensor.*_battery` | Battery % (+ charge attrs on dock) |
| `sensor.*_heater_temperature` | Live chamber temperature |
| `sensor.*_heat_time_remaining` | Seconds left in session |
| `sensor.*_heat_cycle_timer` | Timer with `finishes_at` attribute |
| `sensor.*_operating_state` | Enum: idle, heat_cycle_preheat, … |
| `sensor.*_total_dabs` / `*_trip_dabs` / `*_dabs_per_day` | Odometer |
| `number.*_profile_N_temperature` | Profile setpoint °C (1–4) |
| `number.*_profile_N_duration` | Profile duration seconds (15–120) |
| `select.*_active_profile` | Active profile 1–4 |
| `light.*_lantern` | Logo light — RGB + effects |
| `switch.*_stealth_mode` | Stealth mode |
| `event.*_session` | Fires `started` / `finished` |
| `button.*_reconnect` | Manual BLE reconnect |

**Diagnostics** (disabled by default): `binary_sensor.*_advertising`, `*_connected`, `sensor.*_firmware`, `*_operating_state`. Enable via **Configure → Options → Show diagnostic entities**, then reload.

## Services

Target by **device** or any Puffco entity:

| Service | Description |
|---------|-------------|
| `puffco.start_session` | Optional `profile` 1–4 |
| `puffco.abort_session` | Stop active session |
| `puffco.set_profile` | Switch profile |
| `puffco.reconnect` | Optional `clear_bond: true` |

## Options

**Configure → Puffco → Options**

- Show diagnostic entities
- Block start while charging (default on)
- Faster idle polling

## Automations

**Settings → Automations → Create → Device** — pick your Peak for triggers and actions.

Blueprints ship in `custom_components/puffco/blueprints/`. Copy to `config/blueprints/automation/puffco/` if they do not appear automatically.

## Dashboards

Example Lovelace panels: see [DASHBOARDS.md](DASHBOARDS.md). Files use a `DEVICE_SLUG` placeholder you must replace with your entity prefix.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Connected off after wake | Wait ~15s or press **Reconnect**; close phone app |
| Config flow cannot connect | Pairing mode; remove Peak from Windows Bluetooth settings |
| Lantern color snaps back | Update to latest integration (sync guard fix) |
| Timers show Unknown while idle | Normal on older versions; 1.0.3+ shows **0** when not heating |
| Session event shows Unknown | Normal until the first completed session; check `in_session` attribute |
| Entities go Unknown mid-heat | Update to 1.0.4+ (Peak is busy at target temp; polls now keep last state) |
| Climate target looks very high | HA displays °C as °F — compare to profile temp in the Puffco app (~500°F ≈ 260°C) |
| Proxy timeouts | Use connectable ESPHome Bluetooth proxy |

Debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.puffco: debug
```

## Updating

1. Replace `custom_components/puffco/` (HACS update or manual copy)
2. Restart Home Assistant
3. Check the version in `custom_components/puffco/manifest.json` (or device/integration info in HA).
