"""Constants for Blind Pilot."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "blind_pilot"
SUBENTRY_BLIND = "blind"

# Hub configuration
CONF_WEATHER = "weather_entity"
CONF_OUTDOOR_TEMP = "outdoor_temp_entity"
CONF_LUX = "lux_entity"
CONF_LUX_SUNNY = "lux_sunny"
CONF_BATTERY_SOC = "battery_soc_entity"
CONF_THROTTLE_SOC = "throttle_soc"
CONF_START = "start_time"
CONF_END = "end_time"
CONF_HOLD_HOURS = "hold_hours"
CONF_MIN_MOVE = "min_move"
CONF_MIN_INTERVAL = "min_interval"

# Blind configuration
CONF_NAME = "name"
CONF_COVER = "cover_entity"
CONF_AZIMUTH = "azimuth"
CONF_GLASS_HEIGHT = "glass_height"
CONF_OVERHANG = "overhang"
CONF_PATCH_DEPTH = "patch_depth"
CONF_MIN_POSITION = "min_position"
CONF_DUSK_LOWER = "dusk_lower"
CONF_WAIT_FOR_HAND = "wait_for_hand_open"
CONF_ROOM_TEMP = "room_temp_entity"
CONF_DOOR = "door_entity"
CONF_PV = "pv_entity"
CONF_PV_PEAK = "pv_peak"
CONF_PV_AZIMUTH = "pv_azimuth"
CONF_PV_TILT = "pv_tilt"

DEFAULT_LUX_SUNNY = 30000
DEFAULT_THROTTLE_SOC = 96
DEFAULT_START = "10:00:00"
DEFAULT_END = "23:00:00"
DEFAULT_HOLD_HOURS = 2
DEFAULT_MIN_MOVE = 10
DEFAULT_MIN_INTERVAL = 10

# Settings changed from the dashboard and kept across restarts
SETTING_OBSERVE_ONLY = "observe_only"
SETTING_ENERGY_SAVER = "energy_saver"
SETTING_COOL_DAY_MAX = "cool_day_max"
SETTING_HOT_DAY_MIN = "hot_day_min"
SETTING_ROOM_OPEN_BELOW = "room_open_below"
SETTING_ROOM_SHADE_ABOVE = "room_shade_above"

THRESHOLD_SETTINGS = (
    SETTING_COOL_DAY_MAX,
    SETTING_HOT_DAY_MIN,
    SETTING_ROOM_OPEN_BELOW,
    SETTING_ROOM_SHADE_ABOVE,
)

DEFAULT_SETTINGS = {
    SETTING_OBSERVE_ONLY: True,
    SETTING_ENERGY_SAVER: False,
    SETTING_COOL_DAY_MAX: 20.0,
    SETTING_HOT_DAY_MIN: 26.0,
    SETTING_ROOM_OPEN_BELOW: 24.0,
    SETTING_ROOM_SHADE_ABOVE: 25.0,
}

BLIND_AUTOMATIC = "automatic"
BLIND_WAIT_FOR_HAND = "wait_for_hand_open"

UPDATE_INTERVAL = timedelta(seconds=60)
STARTUP_GRACE = timedelta(minutes=2)  # no moves while other integrations load
TRANSIT_TIMEOUT = timedelta(seconds=90)  # a full travel takes about 45 seconds
FORECAST_INTERVAL = timedelta(minutes=30)
FORECAST_RETRY = timedelta(minutes=5)
SUNNY_ON_DELAY = timedelta(minutes=5)
SUNNY_OFF_DELAY = timedelta(minutes=15)
STORAGE_VERSION = 1
