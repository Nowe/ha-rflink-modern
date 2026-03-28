"""
Constants for the RFLink Modern integration.

This file centralises every magic string, default value, and lookup table
used across the integration so that nothing is scattered or duplicated.
"""

from __future__ import annotations

from homeassistant.const import Platform

# ---------------------------------------------------------------------------
#  Integration identity
# ---------------------------------------------------------------------------
DOMAIN = "rflink_modern"

# ---------------------------------------------------------------------------
#  Supported entity platforms
# ---------------------------------------------------------------------------
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# ---------------------------------------------------------------------------
#  Connection configuration
# ---------------------------------------------------------------------------
CONF_CONNECTION_TYPE = "connection_type"
CONF_PORT = "port"
CONF_HOST = "host"
CONF_TCP_PORT = "tcp_port"
CONF_WAIT_FOR_ACK = "wait_for_ack"
CONF_RECONNECT_INTERVAL = "reconnect_interval"
CONF_TCP_KEEPALIVE_IDLE = "tcp_keepalive_idle_timer"

CONNECTION_SERIAL = "serial"
CONNECTION_TCP = "tcp"

DEFAULT_TCP_PORT = 1234
DEFAULT_RECONNECT_INTERVAL = 10
DEFAULT_TCP_KEEPALIVE_IDLE = 3600

# ---------------------------------------------------------------------------
#  Device / entity behaviour
# ---------------------------------------------------------------------------
CONF_AUTOMATIC_ADD = "automatic_add"
CONF_SIGNAL_REPETITIONS = "signal_repetitions"
CONF_IGNORE_DEVICES = "ignore_devices"

DEFAULT_SIGNAL_REPETITIONS = 1

# Per-entity config keys (used in device YAML / future device config UI)
CONF_ALIASES = "aliases"
CONF_GROUP = "group"
CONF_GROUP_ALIASES = "group_aliases"
CONF_NO_GROUP_ALIASES = "no_group_aliases"
CONF_FIRE_EVENT = "fire_event"
CONF_OFF_DELAY = "off_delay"
CONF_FORCE_UPDATE = "force_update"

# ---------------------------------------------------------------------------
#  Manually configured devices
#
#  Stored in entry.options["devices"] as a dict keyed by device_id:
#
#    {
#      "newkaku_000001_1": {
#        "platform": "switch",
#        "name": "Steckdose Küche"
#      },
#      "rts_0a0a0a_0": {
#        "platform": "cover",
#        "name": "Rollladen Balkon",
#        "cover_type": "inverted",
#        "travel_time_open": 25.0,
#        "travel_time_close": 22.0
#      }
#    }
# ---------------------------------------------------------------------------
CONF_DEVICES = "devices"
CONF_DEVICE_NAME = "name"
CONF_DEVICE_PLATFORM = "platform"

PLATFORM_CHOICES = {
    "light": "💡 Light (Licht)",
    "switch": "🔌 Switch (Schalter)",
    "cover": "🪟 Cover (Rollladen / Jalousie)",
    "binary_sensor": "🚪 Binary Sensor (Kontakt / Bewegung)",
}

# ---------------------------------------------------------------------------
#  Cover types — controls how UP/DOWN map to OPEN/CLOSE
# ---------------------------------------------------------------------------
COVER_TYPE_STANDARD = "standard"       # UP → open,  DOWN → close
COVER_TYPE_INVERTED = "inverted"       # UP → close, DOWN → open  (Somfy RTS)
COVER_TYPE_VENETIAN = "venetian_blind" # UP/DOWN tilt slats, long press full travel

COVER_TYPES = [COVER_TYPE_STANDARD, COVER_TYPE_INVERTED, COVER_TYPE_VENETIAN]

# ---------------------------------------------------------------------------
#  Cover travel-time position tracking
#
#  Because 433 MHz covers never report their actual position, we estimate
#  it by measuring how long the motor has been running.  Two separate
#  durations are needed because most motors travel faster in one direction
#  (gravity helps when closing, spring tension helps when opening, etc.).
#
#  Position convention (matches Home Assistant):
#      0   = fully closed
#    100   = fully open
#
#  A value of 0.0 (or None) disables the timer for that direction.
# ---------------------------------------------------------------------------
CONF_TRAVEL_TIME_OPEN = "travel_time_open"    # seconds from 0 % → 100 %
CONF_TRAVEL_TIME_CLOSE = "travel_time_close"  # seconds from 100 % → 0 %

DEFAULT_TRAVEL_TIME_OPEN = 0.0   # disabled by default
DEFAULT_TRAVEL_TIME_CLOSE = 0.0  # disabled by default

# How often the position is recalculated while the cover is moving.
# Smaller = smoother slider in the UI, but more HA state writes.
POSITION_UPDATE_INTERVAL = 0.5  # seconds

# Protocols that RFLink uses for covers / blinds / shutters
COVER_PROTOCOLS = frozenset({
    "rts", "dooya", "brel", "raex", "screenline", "forest",
    "louvolite", "somfy",
})

# ---------------------------------------------------------------------------
#  Events
# ---------------------------------------------------------------------------
EVENT_BUTTON_PRESSED = "button_pressed"

# ---------------------------------------------------------------------------
#  Runtime data keys (stored in hass.data[DOMAIN][entry_id])
# ---------------------------------------------------------------------------
DATA_ENTITY_LOOKUP = "entity_lookup"
DATA_ENTITY_GROUP_LOOKUP = "entity_group_lookup"
DATA_DEVICE_REGISTER = "device_register"

# ---------------------------------------------------------------------------
#  Sensor type catalogue
#
#  Keys match the field names emitted by the rflink Python library.
#  Each entry defines the default unit and icon.
# ---------------------------------------------------------------------------
SENSOR_TYPES: dict[str, dict[str, str]] = {
    "temperature":     {"unit": "°C",   "icon": "mdi:thermometer"},
    "humidity":        {"unit": "%",    "icon": "mdi:water-percent"},
    "barometer":       {"unit": "hPa",  "icon": "mdi:gauge"},
    "winddirection":   {"unit": "°",    "icon": "mdi:compass-outline"},
    "windgusts":       {"unit": "km/h", "icon": "mdi:weather-windy-variant"},
    "windspeed":       {"unit": "km/h", "icon": "mdi:weather-windy"},
    "windtemp":        {"unit": "°C",   "icon": "mdi:thermometer"},
    "windchill":       {"unit": "°C",   "icon": "mdi:snowflake-thermometer"},
    "rain":            {"unit": "mm",   "icon": "mdi:weather-rainy"},
    "rainrate":        {"unit": "mm/h", "icon": "mdi:weather-pouring"},
    "uv":              {"unit": "UV",   "icon": "mdi:weather-sunny-alert"},
    "forecast":        {"unit": "",     "icon": "mdi:weather-partly-cloudy"},
    "lux":             {"unit": "lx",   "icon": "mdi:brightness-5"},
    "kwatt":           {"unit": "kWh",  "icon": "mdi:lightning-bolt"},
    "watt":            {"unit": "W",    "icon": "mdi:flash"},
    "current_phase_1": {"unit": "A",    "icon": "mdi:current-ac"},
    "current_phase_2": {"unit": "A",    "icon": "mdi:current-ac"},
    "current_phase_3": {"unit": "A",    "icon": "mdi:current-ac"},
    "voltage":         {"unit": "V",    "icon": "mdi:sine-wave"},
    "battery":         {"unit": "",     "icon": "mdi:battery"},
    "co2":             {"unit": "ppm",  "icon": "mdi:molecule-co2"},
    "sound":           {"unit": "dB",   "icon": "mdi:volume-high"},
}
