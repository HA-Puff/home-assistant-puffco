# Changelog

All notable changes to this project are documented here.

## [1.1.12] - 2026-06-08

### Fixed

- **Switch and climate registration** — use the same coordinator + platform base MRO as buttons so Heater and Heat session / Stealth entities register reliably after reload.

## [1.1.11] - 2026-06-08

### Fixed

- **Setup crash** — `PuffcoButtonBase` referenced `ButtonEntity` in `entity.py` without importing it, breaking all platform loading.

## [1.1.10] - 2026-06-08

### Fixed

- **“No longer provided by the integration”** — reload/unload crashed because `async_shutdown` called a non-existent parent method; buttons and other entities were orphaned after reload.
- **Button entity registration** — session buttons use a proper `PuffcoButtonBase` MRO again.

## [1.1.9] - 2026-06-08

### Fixed

- **Stuck BLE connection** — releases the GATT link after ~3 minutes idle so the Peak can sleep; stops the 2s keepalive probe that was preventing disconnect.
- **Reconnect loop** — no longer hammers reconnect when the Peak is asleep (only reconnects on wake adverts), avoiding the “needs pairing mode” recovery trap.
- **Stale link detection** — clears the connected flag when the GATT session is gone but no disconnect callback fired.

### Added

- **Idle disconnect** integration option (on by default) — disable to keep a persistent connection like before.

## [1.1.8] - 2026-06-08

### Fixed

- **Diagnostic entities unavailable** — coordinator stays available with cached data while the Peak is connected (not advertising) or asleep; diagnostic binary sensors use the same persistent availability as other read-only entities.
- **Diagnostics after enable** — entities push cached state when enabled, and turning on “Show diagnostic entities” in integration options re-enables them in the entity registry.

## [1.1.7] - 2026-06-08

### Fixed

- **Reload / remove** — `async_shutdown` now calls the parent coordinator shutdown so interval and reconnect timers stop cleanly.
- **Wake-on-command** — the 5s “wait for Peak to wake” no longer holds the BLE lock, so polls and other commands are not blocked during the wait.

## [1.1.6] - 2026-06-08

### Fixed

- **Button press crash** — logbook calls used the wrong argument order (`name` / `message` swapped), which broke start session and other actions that log to the logbook.

## [1.1.5] - 2026-06-08

### Added

- **`binary_sensor.*_awake`** — shows when the Peak is awake (advertising or connected).
- **Stale-data attributes** — sensors expose `data_stale`, `last_seen`, and `awake` when the Peak is sleeping.
- **Wake-on-command** (optional, on by default) — waits up to 5s for the Peak to advertise before failing a command.

### Changed

- **Controllable entities** (switch, climate, lights, numbers, etc.) go **unavailable** while the Peak is asleep; read-only sensors keep their last value.
- **Session controls** stay available during an active heat timer even if BLE drops briefly.
- **Faster reconnect** when the Peak is already advertising (shorter wake delay).

## [1.1.4] - 2026-06-08

### Fixed

- **Faster commands to the Peak** — start/stop, boost, stealth, and other writes preempt in-flight BLE polls and reconnects instead of queuing behind them. State refresh after writes runs in the background so the GATT command goes out immediately.

## [1.1.3] - 2026-06-08

### Fixed

- **Faster session start** — switch, timer, and session events update immediately after the start command; BLE sync runs in the background instead of blocking up to ~4s.

## [1.1.2] - 2026-06-08

### Fixed

- **Reconnect reliability** — automatic stale-bond healing (unpair + fresh GATT) when the Lorax handshake fails after sleep, instead of requiring delete/re-add. Reconnect worker no longer bails on the first “not visible” attempt and retries up to 8 times.

## [1.1.1] - 2026-06-08

### Added

- **Device picker + active BLE scan** during setup — no longer jumps straight to manual MAC entry when nothing is cached. Choose **Scan for devices…** (15s active scan) or pick from already-discovered Peaks.

## [1.1.0] - 2026-06-08

### Added

- **Boost** — `button.*_boost_session`, `puffco.boost_session` service (during active heat only).
- **Boost presets** — `number.*_profile_N_boost_temp` / `boost_time` per profile.
- **Profile LED color** — `light.*_profile_N_color` (RGB ring color per profile).
- **Profile name** — `text.*_profile_N_name` (read/write).
- **Lantern brightness** — `number.*_lantern_brightness` plus lantern light syncs from device.
- **4-segment LED brightness** — ring / glass / main / battery number entities.
- **Chamber type** — enum sensor (`classic`, `performance`, `xl`, etc.).
- **Diagnostics** — approx dabs remaining, device birthday, uptime, total heat time.
- **Serial number** — written to the HA device registry on full poll.

## [1.0.8] - 2026-06-08

### Fixed

- **Stealth mode** switch now updates reliably on Lorax firmware: 1-byte write (was 4-byte), cached state after writes, and optimistic UI refresh so polls cannot snap the switch back.

## [1.0.7] - 2026-06-08

### Fixed

- **Session finished** / idle events now fire when the cycle ends (session guard no longer blocks real idle transitions; local timer fires `finished` at zero).
- **Charging / dock** — binary sensor is on for any dock state (bulk, topup, full), not only active charge; dock placement fires `charging_started` reliably.

## [1.0.6] - 2026-06-08

### Added

- **`switch.*_heat_session`** — clear on/off for start vs abort (better than climate heat/off).

### Fixed

- Climate **Heat/Off** now matches session state (uses local timer + BLE), always sends abort on off, and skips duplicate starts.

## [1.0.5] - 2026-06-08

### Added

- **Real-time session countdown** — when a heat session starts, a local 1-second timer runs so `heat_time_remaining` and `heat_cycle_timer` tick smoothly even when BLE polls fail. Re-syncs from the device when reads succeed. `finishes_at` is included on session-started events.

## [1.0.4] - 2026-06-08

### Fixed

- Entities no longer go **Unknown** mid-session when the Peak hits target temp: resilient fast-polling keeps last good values if BLE reads fail during active heat.
- Ignore spurious idle operating-state reads while the session timer has not finished.
- Do not disconnect or drop cached state on poll failures during an active heat cycle.
- All entities stay available while cached session data exists.

## [1.0.3] - 2026-06-08

### Fixed

- Heat timers show **0** when idle instead of **Unknown**; `active` attribute indicates session state.
- Session events and entity updates no longer blocked when device registry update fails.
- After starting a session, poll until the Peak reports heat-cycle state so timers and events update.
- Ignore NaN elapsed/total timer reads from the device.

## [1.0.2] - 2026-06-08

### Fixed

- Fix `climate.set_hvac_mode` / session start failing on Home Assistant 2026.x: `async_update_device()` no longer accepts `connections=` (removed redundant update; model/firmware still refresh).

## [1.0.1] - 2026-06-08

### Fixed

- Fix config flow import failure caused by invalid `PuffcoData` dataclass field ordering (`battery_percent` and other required fields were declared after optional fields).

### Documentation

- Remove machine-specific paths (`z:\OneDrive\...`, `Existing-Integration/`) and personal MAC references from docs and examples.
- Dashboard YAMLs use `DEVICE_SLUG` placeholder; see new [docs/DASHBOARDS.md](docs/DASHBOARDS.md).
- Fix `sync_ha_lib` scripts to copy into `_vendor/puffco_ble/` (was pointing at a non-existent path).
- Generalize [PUBLISH.md](docs/PUBLISH.md) for ongoing releases after the initial push.

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
