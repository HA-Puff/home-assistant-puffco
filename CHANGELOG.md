# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-06-08

First public release.

### Home Assistant integration

- Bluetooth discovery config flow (Peak Pro MAC prefixes + service UUIDs)
- Active Bluetooth coordinator with wake reconnect and adaptive polling (2s heat / 10s idle)
- **Climate** entity — profile presets, target temp, start/abort session, `hvac_action`
- Sensors: battery, heater temp, dab counts, heat time remaining, heat cycle timer, enum operating state
- Profile **temperature** and **duration** (15–120s) per profile 1–4
- **Light** — lantern RGB, effects, debounced writes
- **Stealth** switch, session buttons, reconnect button
- **Event** entity for session started/finished
- Domain **services** and **device automations** (triggers + actions)
- Options: diagnostics visibility, block start while charging, fast idle poll
- Repair flow when reconnect fails; logbook entries for sessions and connectivity
- Automation **blueprints** (session notify, lantern on start, charging notice)
- Diagnostic entities disabled by default
- Flat (Firmware X) and Lorax (Firmware AG+) BLE protocols

### puffco-ble library (vendored under `custom_components/puffco/_vendor/`)

- Authenticated GATT client with Lorax sticky-handle prune
- CLI for scan, info, dabs, temps, session, lantern

### Known limitations

- Peak Pro focus; other Puffco models untested
- Profile LED colors, boost, vapor setting not yet exposed in HA
- Close the official Puffco app before connecting (single BLE master)
- Full HA restart required after install or major updates

[1.0.0]: https://github.com/HA-Puff/home-assistant-puffco/releases/tag/v1.0.0
