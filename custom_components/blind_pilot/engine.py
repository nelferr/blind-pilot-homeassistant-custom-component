"""Decision logic for Blind Pilot.

This module has no Home Assistant imports so the rules can be unit tested on
their own. Positions follow the Home Assistant convention: 0 is fully lowered,
100 is fully raised. The blind is assumed to lower from the top of the glass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

MIN_ELEVATION = 2.0  # degrees; at or below this the day is treated as over
MAX_SIDE_ANGLE = 85.0  # degrees between the sun and the window normal
MIN_SUNLIT_HEIGHT = 0.05  # metres of sunlit glass that count as "sun on the glass"
POSITION_STEP = 5  # glare positions are rounded to this
CLOSED_MAX = 2  # positions at or below this count as closed
POSITION_TOLERANCE = 3  # smaller differences are not treated as a move

MODE_HEAT = "heat"
MODE_SHADE = "shade"
MODE_GLARE = "glare"

DAY_COOL = "cool"
DAY_MILD = "mild"
DAY_HOT = "hot"

STATUS_ACTIVE = "active"
STATUS_OBSERVING = "observing"
STATUS_HOLD = "manual_hold"
STATUS_WAITING = "waiting_for_hand_open"
STATUS_OUTSIDE_HOURS = "outside_hours"
STATUS_DOOR_OPEN = "door_open"
STATUS_DISABLED = "disabled"
STATUS_UNAVAILABLE = "cover_unavailable"

MOVE_CLOSED = "closed"
MOVE_RAISED = "raised"
MOVE_LOWERED = "lowered"

PV_SUNNY_RATIO = 0.55  # share of clear-sky output that proves direct sun
PV_CLOUDY_RATIO = 0.35  # share below which the sky is treated as overcast
PV_MIN_ELEVATION = 8.0  # the clear-sky model is too rough below this
PV_MIN_EXPECTED = 150.0  # watts; below this the ratio is mostly noise
LUX_MIN_ELEVATION = 5.0
LUX_CLOUDY_FACTOR = 0.6

SOURCE_LUX = "lux"
SOURCE_PV = "pv"
SOURCE_PV_THROTTLED = "pv_throttled"
SOURCE_WEATHER = "weather"

_SUNNY_CONDITIONS = {"sunny", "windy", "clear-night"}
_PARTLY_CONDITIONS = {"partlycloudy", "windy-variant"}
_PARTLY_MAX_CLOUD = 85.0


@dataclass(frozen=True)
class BlindGeometry:
    """Fixed facts about one window and its blind."""

    azimuth: float  # compass bearing the glass faces
    glass_height: float  # metres, floor to top of glass
    overhang: float = 0.0  # metres the overhang projects at the top of the glass
    patch_depth: float = 1.0  # metres the sun may reach into the room
    min_position: int = 15  # lowest position used when shading
    dusk_lower: bool = True


@dataclass(frozen=True)
class Thresholds:
    """Temperatures that decide whether sun is welcome."""

    cool_day_max: float = 20.0
    hot_day_min: float = 26.0
    room_open_below: float = 24.0
    room_shade_above: float = 25.0


@dataclass(frozen=True)
class SunOnGlass:
    """Where the sun is relative to one window."""

    on_glass: bool
    profile_angle: float | None  # degrees, sun height seen in the window's section
    sunlit_height: float  # metres of glass in direct sun, measured from the floor
    blocked_by: str | None  # "horizon", "side" or "overhang"


@dataclass(frozen=True)
class Decision:
    """What the rules want for one blind right now."""

    target: int | None  # None means leave the blind where it is
    reason: str
    mode: str | None


@dataclass
class BlindState:
    """What Blind Pilot remembers about one blind between updates."""

    armed: bool = False
    armed_day: str | None = None  # ISO date the arming rule was evaluated for
    hold_until: datetime | None = None
    expected_position: int | None = None
    command_time: datetime | None = None
    last_move: datetime | None = None


def sun_on_glass(elevation: float, azimuth: float, geometry: BlindGeometry) -> SunOnGlass:
    """Work out whether direct sun reaches the glass, and how much of it."""
    if elevation <= MIN_ELEVATION:
        return SunOnGlass(False, None, 0.0, "horizon")
    side = (azimuth - geometry.azimuth + 180) % 360 - 180
    if abs(side) >= MAX_SIDE_ANGLE:
        return SunOnGlass(False, None, 0.0, "side")
    profile = math.degrees(
        math.atan2(math.tan(math.radians(elevation)), math.cos(math.radians(side)))
    )
    shaded = geometry.overhang * math.tan(math.radians(profile))
    sunlit = max(0.0, geometry.glass_height - shaded)
    if sunlit <= MIN_SUNLIT_HEIGHT:
        return SunOnGlass(False, profile, 0.0, "overhang")
    return SunOnGlass(True, profile, sunlit, None)


def day_type(day_high: float | None, thresholds: Thresholds) -> str:
    """Classify the day from its expected high."""
    if day_high is None:
        return DAY_MILD
    if day_high < thresholds.cool_day_max:
        return DAY_COOL
    if day_high > thresholds.hot_day_min:
        return DAY_HOT
    return DAY_MILD


def thermal_mode(day: str, room_temp: float | None, thresholds: Thresholds) -> str:
    """Decide whether sun on the glass should be let in, blocked or just tamed."""
    if day == DAY_HOT:
        return MODE_SHADE
    if day == DAY_COOL:
        if room_temp is not None and room_temp > thresholds.room_shade_above + 0.5:
            return MODE_SHADE
        return MODE_HEAT
    if room_temp is None:
        return MODE_GLARE
    if room_temp < thresholds.room_open_below:
        return MODE_HEAT
    if room_temp > thresholds.room_shade_above:
        return MODE_SHADE
    return MODE_GLARE


def decide(
    geometry: BlindGeometry,
    thresholds: Thresholds,
    *,
    elevation: float | None,
    azimuth: float | None,
    sunny: bool | None,
    day: str,
    room_temp: float | None,
    energy_saver: bool = False,
) -> Decision:
    """Return the position the rules want. An unknown sky is treated as sunny."""
    if elevation is None or azimuth is None:
        return Decision(None, "Sun position unknown", None)

    floor = 0 if energy_saver else geometry.min_position

    if elevation <= MIN_ELEVATION:
        if energy_saver or geometry.dusk_lower:
            return Decision(0, "Sun is down: lowered", None)
        return Decision(None, "Sun is down: left as it is", None)

    sun = sun_on_glass(elevation, azimuth, geometry)
    if not sun.on_glass or sunny is False:
        if sun.on_glass:
            why = "Cloudy"
        elif sun.blocked_by == "overhang":
            why = "Overhang is shading the glass"
        else:
            why = "No direct sun on the glass"
        if not energy_saver:
            return Decision(100, f"{why}: open", None)
        if day == DAY_MILD:
            return Decision(None, f"{why}: energy saver leaves it as it is", None)
        return Decision(0, f"{why}: energy saver keeps it closed", None)

    mode = thermal_mode(day, room_temp, thresholds)
    if mode == MODE_HEAT:
        return Decision(100, "Sun on the glass and heat is welcome: open", mode)

    if mode == MODE_SHADE:
        floor_height = geometry.glass_height * floor / 100
        if sun.sunlit_height <= floor_height + MIN_SUNLIT_HEIGHT:
            return Decision(100, "Overhang shades everything above the gap: open", mode)
        return Decision(floor, "Sun on the glass and the room should stay cool: shading", mode)

    # The blind's lower edge sets how high the sun can enter, and so how far it reaches.
    open_height = geometry.patch_depth * math.tan(math.radians(sun.profile_angle))
    if sun.sunlit_height <= open_height:
        return Decision(100, "Sun stays near the window: open", mode)
    position = open_height / geometry.glass_height * 100
    position = int(round(position / POSITION_STEP) * POSITION_STEP)
    position = max(floor, min(100, position))
    return Decision(position, "Limiting how far the sun reaches into the room", mode)


def refresh_arming(
    state: BlindState,
    today: str,
    in_window: bool,
    position: int | None,
    wait_for_hand: bool,
) -> None:
    """Apply the once-a-day arming rule at the start of the active hours."""
    if not in_window:
        state.armed = False
        state.armed_day = None
        return
    if state.armed_day == today or position is None:
        return
    state.armed = (not wait_for_hand) or position > CLOSED_MAX
    state.armed_day = today


def apply_manual_move(
    state: BlindState,
    from_position: int | None,
    to_position: int,
    now: datetime,
    hold: timedelta,
) -> str:
    """Record a move somebody made by hand and return what kind it was."""
    state.hold_until = now + hold
    state.expected_position = to_position
    if to_position <= CLOSED_MAX:
        state.armed = False
        return MOVE_CLOSED
    if from_position is None or to_position > from_position:
        state.armed = True
        return MOVE_RAISED
    return MOVE_LOWERED


def control_status(
    *,
    automatic: bool,
    in_window: bool,
    door_open: bool,
    state: BlindState,
    now: datetime,
    energy_saver: bool,
) -> str:
    """Say whether the blind may be moved right now, and if not, why."""
    if not automatic:
        return STATUS_DISABLED
    if not in_window:
        return STATUS_OUTSIDE_HOURS
    if door_open:
        return STATUS_DOOR_OPEN
    if state.hold_until is not None and now < state.hold_until:
        return STATUS_HOLD
    if not state.armed and not energy_saver:
        return STATUS_WAITING
    return STATUS_ACTIVE


def should_move(
    target: int | None,
    position: int | None,
    state: BlindState,
    now: datetime,
    min_move: int,
    min_interval: timedelta,
) -> bool:
    """Filter out small or frequent adjustments."""
    if target is None or position is None:
        return False
    delta = abs(target - position)
    if delta <= POSITION_TOLERANCE:
        return False
    if state.last_move is not None and now - state.last_move < min_interval:
        return False
    if delta >= min_move:
        return True
    return target in (0, 100)


def clear_sky_fraction(
    elevation: float, azimuth: float, panel_azimuth: float, panel_tilt: float
) -> float:
    """Share of a panel string's clear-sky peak expected for this sun position."""
    if elevation <= 0:
        return 0.0
    sun = math.radians(elevation)
    tilt = math.radians(panel_tilt)
    incidence = math.sin(sun) * math.cos(tilt) + math.cos(sun) * math.sin(
        tilt
    ) * math.cos(math.radians(azimuth - panel_azimuth))
    air_mass = 1 / max(math.sin(sun), 0.05)
    direct = 0.7 ** (air_mass**0.678) / 0.7
    return max(0.0, incidence) * direct + 0.08


def assess_sunny(
    *,
    elevation: float | None,
    azimuth: float | None,
    lux: float | None = None,
    lux_sunny: float = 30000.0,
    pv_power: float | None = None,
    pv_peak: float = 0.0,
    pv_azimuth: float = 180.0,
    pv_tilt: float = 25.0,
    throttled: bool = False,
    condition: str | None = None,
    cloud_coverage: float | None = None,
    previous: bool | None = None,
) -> tuple[bool | None, str | None]:
    """Judge whether the sun is out, from the best source available.

    Returns the raw reading and the source it came from. None means "no new
    evidence", and the caller keeps its last value.
    """
    if elevation is None or azimuth is None:
        return None, None

    if lux is not None and elevation >= LUX_MIN_ELEVATION:
        scale = min(1.0, max(0.3, math.sin(math.radians(elevation)) / 0.5))
        threshold = lux_sunny * scale
        if lux >= threshold:
            return True, SOURCE_LUX
        if lux <= threshold * LUX_CLOUDY_FACTOR:
            return False, SOURCE_LUX
        return previous, SOURCE_LUX

    weather = _sunny_from_weather(condition, cloud_coverage)

    if pv_power is not None and pv_peak > 0 and elevation >= PV_MIN_ELEVATION:
        expected = pv_peak * clear_sky_fraction(elevation, azimuth, pv_azimuth, pv_tilt)
        if expected >= PV_MIN_EXPECTED:
            ratio = pv_power / expected
            if ratio >= PV_SUNNY_RATIO:
                return True, SOURCE_PV
            if throttled:
                # A throttled inverter reads low whatever the sky is doing, so
                # only clearly bad weather is allowed to change the answer.
                return (False if weather is False else None), SOURCE_PV_THROTTLED
            if ratio <= PV_CLOUDY_RATIO:
                return False, SOURCE_PV
            return previous, SOURCE_PV

    return weather, SOURCE_WEATHER


def _sunny_from_weather(condition: str | None, cloud_coverage: float | None) -> bool | None:
    if condition is None:
        return None
    if condition in _SUNNY_CONDITIONS:
        return True
    if condition in _PARTLY_CONDITIONS:
        return cloud_coverage is None or cloud_coverage < _PARTLY_MAX_CLOUD
    return False


@dataclass
class Debouncer:
    """Hold a yes/no reading steady until a change has lasted long enough."""

    on_delay: timedelta
    off_delay: timedelta
    value: bool | None = None
    _candidate: bool | None = None
    _since: datetime | None = None

    def update(self, raw: bool | None, now: datetime) -> bool | None:
        """Feed a new reading and return the steady value."""
        if raw is None or raw == self.value:
            self._candidate = None
            return self.value
        if self.value is None:
            self.value = raw
            return raw
        if self._candidate != raw:
            self._candidate = raw
            self._since = now
        delay = self.on_delay if raw else self.off_delay
        if now - self._since >= delay:
            self.value = raw
            self._candidate = None
        return self.value
