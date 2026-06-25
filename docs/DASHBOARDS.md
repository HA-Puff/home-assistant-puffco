# Example dashboards

Optional Lovelace layouts live in this folder:

- `dashboard-peak-pro-holotape.yaml` — **recommended** Pip-Boy terminal panel (Mushroom + apexcharts, matches home-dev style)
- `dashboard-peak-pro-node-snippet.yaml` — rows + console link to paste into NODE_02 R&D_OFFICE
- `dashboard-peak-pro-pipboy.yaml` — legacy three-column layout

Both are **examples**, not drop-in configs. Entity IDs depend on your Peak’s name and MAC.

## Before you paste

1. Add the Puffco integration and confirm entities exist (**Developer tools → States**, filter `peak_pro`).
2. **Create helper** `input_select.peak_pro_profile_view` — see `dashboard-peak-pro-helpers.yaml` (instant profile chip switching; no BLE).
3. Open `dashboard-peak-pro-holotape.yaml` — entity IDs use prefix `peak_pro_00059_0c_43_14_b7_91_9c`.
4. Paste into **Settings → Dashboards → Raw configuration editor**.

The holotape panel uses **Mushroom Cards**, **card_mod** (profile show/hide), and **apexcharts-card** (optional). All temperature labels are **°C** (matches the integration). Change device profile on the **climate** card; P1–P4 chips only pick which profile settings to edit.

## Entity naming

Integration entities follow Home Assistant’s usual pattern:

| Pattern | Example |
|---------|---------|
| `climate.{slug}_heater` | Session control |
| `sensor.{slug}_battery` | Battery % |
| `sensor.{slug}_heater_temperature` | Chamber temp |
| `sensor.{slug}_daily_dabs` | Daily dabs (integration key `dabs_per_day`; HA may slug either way) |
| `sensor.{slug}_heat_time_remaining` | Live session countdown (seconds) |
| `sensor.{slug}_heat_cycle_timer` | Countdown + `finishes_at` attribute |
| `sensor.{slug}_chamber_type` | Atomizer / chamber type (diagnostics option) |
| `sensor.{slug}_approx_dabs_remaining` | Estimated dabs left |
| `event.{slug}_session` | Session started/finished/phase events |
| `light.{slug}_profile_N_color` | Per-profile accent color (N=1–4) |
| `text.{slug}_profile_N_name` | Per-profile display name |
| `button.{slug}_boost_session` | Mid-session boost |
| `switch.{slug}_heat_session` | Start/stop session toggle |

Legacy session **buttons** are referenced in these samples; you can swap tap actions to `climate.set_hvac_mode` on `climate.{slug}_heater` if you prefer the native climate control.
