# Puffco Home Assistant

Unofficial Bluetooth integration for **Puffco Peak Pro** in [Home Assistant](https://www.home-assistant.io/).

Control heat sessions, profiles, lantern lighting, and read dab metrics locally — no cloud account required.

> **Beta.** This integration is under active development. Expect rough edges, breaking changes between releases, and report issues on [GitHub](https://github.com/HA-Puff/home-assistant-puffco/issues).
>
> **Not affiliated with Puffco.** Use at your own risk. MIT licensed.
>
> **How this was built.** Much of the code was written with AI assistance (Cursor) and **manually reviewed** before merge. The maintainer has prior Python experience and tests changes on real hardware, but this is not a from-scratch hand-written project — review the code and use your own judgment before relying on it for anything critical.

## Install

### HACS (recommended)

1. Add this repository as a [custom HACS repository](https://hacs.xyz/docs/faq/custom_repositories/) (category: **Integration**).
2. Install **Puffco** from HACS.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → Puffco**
5. Put the Peak in pairing mode (hold power until the blue light bar) for first setup only.

### Manual

1. Copy `custom_components/puffco/` to `/config/custom_components/puffco/`
2. Restart Home Assistant (full restart, not reload).
3. Add the integration from the UI.

See [docs/DEPLOY.md](docs/DEPLOY.md) for entity reference and troubleshooting.

## Requirements

- Home Assistant **2024.6** or newer
- Bluetooth adapter or **connectable** Bluetooth proxy (ESPHome)
- Peak Pro with firmware **X** (flat) or **AG+** (Lorax) — see [docs/PREREQUISITES.md](docs/PREREQUISITES.md)

## Features

| Area | What's included |
|------|-----------------|
| **Session** | Climate entity (start/abort, timer, preheat/active/fade) |
| **Profiles** | Temp + duration (1–4), active profile select |
| **Metrics** | Total/trip/daily dabs, heater temp, battery, charging |
| **Lantern** | RGB light, effects (Solid, Breathing, Pulsing, …) |
| **Automations** | Device triggers, services, event entity, blueprints |
| **Reliability** | Auto-reconnect on wake, repair issue on link failure |

## Primary entities

After setup, use these first:

- `switch.*_heat_session` — **start/stop** a dab session (recommended)
- `climate.*_heater` — profile preset + target temp (optional; use switch for on/off)
- `sensor.*_battery` / `*_heater_temperature` / `*_heat_cycle_timer`
- `number.*_profile_N_temperature` / `*_profile_N_duration`
- `light.*_lantern`

Legacy buttons (`start_session`, `abort_session`) still exist; climate is the native control surface.

## Development

The BLE library lives in [`puffco-ble/`](puffco-ble/) for standalone testing. The HA integration vendors a copy at `custom_components/puffco/_vendor/puffco_ble/`.

```powershell
cd puffco-ble
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
puffco-cli scan
```

Sync library → integration after BLE changes (copies into `_vendor/`, excludes CLI):

```powershell
.\scripts\sync_ha_lib.ps1
```

```bash
./scripts/sync_ha_lib.sh
```

## Publishing / releases

Maintainers: see [docs/PUBLISH.md](docs/PUBLISH.md). Repo: [github.com/HA-Puff/home-assistant-puffco](https://github.com/HA-Puff/home-assistant-puffco).

## Credits

Built on community reverse-engineering of the Peak Pro BLE protocol and prior work such as [PuffcoPC](https://github.com/meekzyr/PuffcoPC).

## License

MIT — see [LICENSE](LICENSE).
