"""Constants for the Puffco Home Assistant integration."""

DOMAIN = "puffco"

CONF_MAC = "mac"

# Config entry options
CONF_SHOW_DIAGNOSTICS = "show_diagnostics"
CONF_BLOCK_START_WHILE_CHARGING = "block_start_while_charging"
CONF_FAST_POLL = "fast_poll"
CONF_WAKE_ON_COMMAND = "wake_on_command"
CONF_IDLE_DISCONNECT = "idle_disconnect"

DEFAULT_SHOW_DIAGNOSTICS = False
DEFAULT_BLOCK_START_WHILE_CHARGING = True
DEFAULT_FAST_POLL = False
DEFAULT_WAKE_ON_COMMAND = True
DEFAULT_IDLE_DISCONNECT = True

# Entity labels (Settings → Entities → Labels)
LABEL_PROFILE = "puffco_profile"
LABEL_SESSION = "puffco_session"
LABEL_CONNECTIVITY = "puffco_connectivity"

# Bus events for device automations
EVENT_SESSION_STARTED = f"{DOMAIN}_session_started"
EVENT_SESSION_FINISHED = f"{DOMAIN}_session_finished"
EVENT_DISCONNECTED = f"{DOMAIN}_disconnected"
EVENT_CHARGING_STARTED = f"{DOMAIN}_charging_started"

# Boost preset limits (added temp/time during an active session).
BOOST_TEMP_FLOOR_C = 0.0
BOOST_TEMP_CEILING_C = 50.0
BOOST_TIME_FLOOR_S = 0
BOOST_TIME_CEILING_S = 60
LED_BRIGHTNESS_MIN = 0
LED_BRIGHTNESS_MAX = 255

# Diagnostic entities disabled by default (unique_id suffix after mac_)
DIAGNOSTIC_ENTITY_SUFFIXES = (
    "_advertising",
    "_connected",
    "_charging",
    "_firmware",
    "_operating_state",
    "_chamber_type",
    "_approx_dabs_remaining",
    "_device_birthday",
    "_uptime",
    "_total_heat_time",
)

DEFAULT_SCAN_INTERVAL = 60
# Background poll while connected. Advert-driven polls stop once the Peak
# connects (it no longer advertises), so this keeps sensors fresh.
POLL_INTERVAL = 10
# Faster poll while preheating / heating / cooling down after a dab.
HEAT_POLL_INTERVAL = 2
HEAT_CYCLE_STATES = frozenset(
    {
        "heat_cycle_preheat",
        "heat_cycle_active",
        "heat_cycle_fade",
    }
)
# Event entity types — session boundaries plus each heat-cycle phase from BLE.
SESSION_EVENT_TYPES: tuple[str, ...] = (
    "started",
    "finished",
    "heat_cycle_preheat",
    "heat_cycle_active",
    "heat_cycle_fade",
)
# Full sensor sweep every N background polls (dab counts, all profile temps).
FULL_POLL_EVERY = 6
# How often to retry BLE connect while the Peak is awake but not linked.
RECONNECT_INTERVAL = 15
# Pause after wake advert before GATT connect (Peak/proxy need a moment).
RECONNECT_WAKE_DELAY = 1.0
RECONNECT_WAKE_DELAY_ADVERTISING = 0.2
RECONNECT_MAX_ATTEMPTS = 8
# Wait for the Peak to advertise before failing a user command (asleep / out of range).
WAKE_ON_COMMAND_TIMEOUT = 5.0
WAKE_ON_COMMAND_POLL = 0.3
# Release the GATT link after idle so the Peak can sleep (battery-friendly).
IDLE_DISCONNECT_SECONDS = 180
# Debounce rapid lantern color picker updates before hitting BLE.
LANTERN_WRITE_DEBOUNCE = 0.35
# Ignore coordinator lantern parse briefly after a local write (poll races debounce).
LANTERN_SYNC_GUARD = 2.0
SESSION_START_POLL_INTERVAL = 0.35
SESSION_START_POLL_ATTEMPTS = 6
STEALTH_SYNC_GUARD = 2.0

ATTR_PROTOCOL = "protocol"
ATTR_FIRMWARE = "firmware"
ATTR_ACTIVE_PROFILE = "active_profile"
ATTR_OPERATING_STATE = "operating_state"

PROFILE_COUNT = 4

TEMPERATURE_FLOOR_C = 200.0
TEMPERATURE_CEILING_C = 320.0
# Peak app heat-cycle duration limits (seconds).
PROFILE_TIME_FLOOR_S = 15
PROFILE_TIME_CEILING_S = 120


def is_heat_cycle_state(state: str | None) -> bool:
    """True while the Peak is in a heat session (preheat through fade)."""
    return state in HEAT_CYCLE_STATES
