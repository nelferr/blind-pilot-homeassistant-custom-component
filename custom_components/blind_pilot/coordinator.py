"""Coordinator: reads Home Assistant state, runs the engine and moves the covers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    BLIND_AUTOMATIC,
    BLIND_WAIT_FOR_HAND,
    CONF_AZIMUTH,
    CONF_BATTERY_SOC,
    CONF_COVER,
    CONF_DOOR,
    CONF_DUSK_LOWER,
    CONF_END,
    CONF_GLASS_HEIGHT,
    CONF_HOLD_HOURS,
    CONF_LIMIT_GLARE,
    CONF_LUX,
    CONF_LUX_SUNNY,
    CONF_MIN_INTERVAL,
    CONF_MIN_MOVE,
    CONF_MIN_POSITION,
    CONF_OUTDOOR_TEMP,
    CONF_OVERHANG,
    CONF_PATCH_DEPTH,
    CONF_PV,
    CONF_PV_AZIMUTH,
    CONF_PV_PEAK,
    CONF_PV_TILT,
    CONF_ROOM_TEMP,
    CONF_START,
    CONF_THROTTLE_SOC,
    CONF_WAIT_FOR_HAND,
    CONF_WEATHER,
    DEFAULT_END,
    DEFAULT_HOLD_HOURS,
    DEFAULT_LUX_SUNNY,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_MIN_MOVE,
    DEFAULT_SETTINGS,
    DEFAULT_START,
    DEFAULT_THROTTLE_SOC,
    DOMAIN,
    FORECAST_INTERVAL,
    FORECAST_RETRY,
    SETTING_ENERGY_SAVER,
    SETTING_OBSERVE_ONLY,
    STARTUP_GRACE,
    STORAGE_VERSION,
    SUBENTRY_BLIND,
    SUNNY_OFF_DELAY,
    SUNNY_ON_DELAY,
    THRESHOLD_SETTINGS,
    TRANSIT_TIMEOUT,
    UPDATE_INTERVAL,
)
from .engine import (
    DAY_MILD,
    POSITION_TOLERANCE,
    STATUS_ACTIVE,
    STATUS_OBSERVING,
    STATUS_UNAVAILABLE,
    BlindGeometry,
    BlindState,
    DayHigh,
    Debouncer,
    Thresholds,
    apply_manual_move,
    assess_sunny,
    control_status,
    cool_outside_now,
    day_type,
    decide,
    refresh_arming,
    should_move,
    sun_on_glass,
)

_LOGGER = logging.getLogger(__name__)

type BlindPilotConfigEntry = ConfigEntry[BlindPilotCoordinator]

_MOVING_STATES = ("opening", "closing")
_NO_VALUE = (STATE_UNAVAILABLE, STATE_UNKNOWN)


@dataclass
class BlindSnapshot:
    """What the entities show for one blind."""

    position: int | None = None
    target: int | None = None
    reason: str = "Starting"
    mode: str | None = None
    status: str = STATUS_UNAVAILABLE
    sunny: bool | None = None
    sunny_source: str | None = None
    sun_on_glass: bool = False
    profile_angle: float | None = None
    sunlit_height: float | None = None
    room_temp: float | None = None


class BlindRuntime:
    """One configured blind and everything remembered about it."""

    def __init__(self, blind_id: str, name: str, conf: dict[str, Any]) -> None:
        self.blind_id = blind_id
        self.name = name
        self.conf = conf
        self.geometry = BlindGeometry(
            azimuth=float(conf[CONF_AZIMUTH]),
            glass_height=float(conf[CONF_GLASS_HEIGHT]),
            overhang=float(conf.get(CONF_OVERHANG, 0)),
            patch_depth=float(conf.get(CONF_PATCH_DEPTH, 1)),
            min_position=int(conf.get(CONF_MIN_POSITION, 15)),
            dusk_lower=bool(conf.get(CONF_DUSK_LOWER, True)),
            limit_glare=bool(conf.get(CONF_LIMIT_GLARE, True)),
        )
        self.state = BlindState()
        self.sunny = Debouncer(SUNNY_ON_DELAY, SUNNY_OFF_DELAY)
        self.automatic = True
        self.wait_for_hand = bool(conf.get(CONF_WAIT_FOR_HAND, True))
        self.snapshot = BlindSnapshot()


class BlindPilotCoordinator(DataUpdateCoordinator[dict[str, BlindSnapshot]]):
    """Runs the rules once a minute and whenever a cover or door changes."""

    config_entry: BlindPilotConfigEntry

    def __init__(self, hass: HomeAssistant, entry: BlindPilotConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        # The options form replaces the whole hub configuration once it has been saved.
        self.conf: dict[str, Any] = dict(entry.options or entry.data)
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.blinds: dict[str, BlindRuntime] = {
            subentry.subentry_id: BlindRuntime(
                subentry.subentry_id, subentry.title, dict(subentry.data)
            )
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_BLIND
        }
        self.day: str = DAY_MILD
        self.day_high: float | None = None
        self.outdoor_temp: float | None = None
        self.cool_outside = False
        self._day_high = DayHigh()
        self._start = _parse_time(self.conf.get(CONF_START), DEFAULT_START)
        self._end = _parse_time(self.conf.get(CONF_END), DEFAULT_END)
        self._hold = timedelta(hours=float(self.conf.get(CONF_HOLD_HOURS, DEFAULT_HOLD_HOURS)))
        self._min_move = int(self.conf.get(CONF_MIN_MOVE, DEFAULT_MIN_MOVE))
        self._min_interval = timedelta(
            minutes=float(self.conf.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL))
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._saved: dict[str, Any] | None = None
        self._started = dt_util.utcnow()
        self._forecast_high: float | None = None
        self._forecast_checked: datetime | None = None

    async def async_load(self) -> None:
        """Restore settings and per-blind memory from storage."""
        stored = await self._store.async_load() or {}
        peak = stored.get("day_high") or {}
        self._day_high = DayHigh(peak.get("day"), peak.get("value"))
        self.settings.update(
            {k: v for k, v in stored.get("settings", {}).items() if k in DEFAULT_SETTINGS}
        )
        for blind_id, data in stored.get("blinds", {}).items():
            blind = self.blinds.get(blind_id)
            if blind is None:
                continue
            blind.automatic = data.get(BLIND_AUTOMATIC, blind.automatic)
            blind.wait_for_hand = data.get(BLIND_WAIT_FOR_HAND, blind.wait_for_hand)
            blind.state.armed = data.get("armed", False)
            blind.state.armed_day = data.get("armed_day")
            blind.state.hold_until = _parse_datetime(data.get("hold_until"))
            blind.state.last_move = _parse_datetime(data.get("last_move"))
        self._saved = self._data_to_save()

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Re-run the rules as soon as a cover or door changes."""
        entities = [blind.conf[CONF_COVER] for blind in self.blinds.values()]
        entities += [
            blind.conf[CONF_DOOR] for blind in self.blinds.values() if blind.conf.get(CONF_DOOR)
        ]
        if not entities:
            return lambda: None
        return async_track_state_change_event(self.hass, entities, self._handle_state_change)

    @callback
    def _handle_state_change(self, event: Event) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    async def async_save_now(self) -> None:
        """Write storage immediately, used when unloading."""
        self._saved = self._data_to_save()
        await self._store.async_save(self._saved)

    async def async_set_setting(self, key: str, value: Any) -> None:
        """Change a hub setting from an entity."""
        self.settings[key] = value
        await self.async_refresh()

    async def async_set_blind_flag(self, blind_id: str, key: str, value: bool) -> None:
        """Change a per-blind switch from an entity."""
        blind = self.blinds[blind_id]
        if key == BLIND_AUTOMATIC:
            blind.automatic = value
        else:
            blind.wait_for_hand = value
        await self.async_refresh()

    async def async_resume(self, blind_id: str) -> None:
        """End a manual hold and let the rules take the blind again."""
        state = self.blinds[blind_id].state
        state.hold_until = None
        state.armed = True
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, BlindSnapshot]:
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        in_window = self._start <= local.time() < self._end
        today = local.date().isoformat()

        elevation = azimuth = None
        if (sun := self.hass.states.get("sun.sun")) is not None:
            elevation = sun.attributes.get("elevation")
            azimuth = sun.attributes.get("azimuth")

        await self._async_refresh_forecast(now)
        self.outdoor_temp = self._float_state(self.conf.get(CONF_OUTDOOR_TEMP))
        self.day_high = self._day_high.update(today, self._forecast_high, self.outdoor_temp)
        thresholds = Thresholds(**{key: float(self.settings[key]) for key in THRESHOLD_SETTINGS})
        self.day = day_type(self.day_high, thresholds)
        self.cool_outside = cool_outside_now(
            self.outdoor_temp, thresholds.cool_day_max, self.cool_outside
        )

        condition = cloud = None
        weather = self.hass.states.get(self.conf[CONF_WEATHER])
        if weather is not None and weather.state not in _NO_VALUE:
            condition = weather.state
            cloud = weather.attributes.get("cloud_coverage")

        soc = self._float_state(self.conf.get(CONF_BATTERY_SOC))
        throttled = soc is not None and soc >= float(
            self.conf.get(CONF_THROTTLE_SOC, DEFAULT_THROTTLE_SOC)
        )
        lux = self._float_state(self.conf.get(CONF_LUX))
        may_move = (
            not self.settings[SETTING_OBSERVE_ONLY] and now - self._started >= STARTUP_GRACE
        )

        for blind in self.blinds.values():
            position, moving = self._read_cover(blind)
            self._track_manual_moves(blind, position, moving, now)
            refresh_arming(blind.state, today, in_window, position, blind.wait_for_hand)

            raw, source = assess_sunny(
                elevation=elevation,
                azimuth=azimuth,
                lux=lux,
                lux_sunny=float(self.conf.get(CONF_LUX_SUNNY, DEFAULT_LUX_SUNNY)),
                pv_power=self._float_state(blind.conf.get(CONF_PV)),
                pv_peak=float(blind.conf.get(CONF_PV_PEAK, 0)),
                pv_azimuth=float(blind.conf.get(CONF_PV_AZIMUTH, 180)),
                pv_tilt=float(blind.conf.get(CONF_PV_TILT, 25)),
                throttled=throttled,
                condition=condition,
                cloud_coverage=cloud,
                previous=blind.sunny.value,
            )
            sunny = blind.sunny.update(raw, now)
            room_temp = self._float_state(blind.conf.get(CONF_ROOM_TEMP))
            energy_saver = bool(self.settings[SETTING_ENERGY_SAVER])

            decision = decide(
                blind.geometry,
                thresholds,
                elevation=elevation,
                azimuth=azimuth,
                sunny=sunny,
                day=self.day,
                room_temp=room_temp,
                cool_outside=self.cool_outside,
                energy_saver=energy_saver,
            )

            door = self.hass.states.get(blind.conf.get(CONF_DOOR) or "")
            status = control_status(
                automatic=blind.automatic,
                in_window=in_window,
                door_open=door is not None and door.state == STATE_ON,
                state=blind.state,
                now=now,
                energy_saver=energy_saver,
            )
            if position is None:
                status = STATUS_UNAVAILABLE
            elif status == STATUS_ACTIVE:
                if self.settings[SETTING_OBSERVE_ONLY]:
                    status = STATUS_OBSERVING
                elif (
                    may_move
                    and not moving
                    and should_move(
                        decision.target,
                        position,
                        blind.state,
                        now,
                        self._min_move,
                        self._min_interval,
                    )
                ):
                    self._move(blind, decision.target, decision.reason, now)

            snapshot = BlindSnapshot(
                position=position,
                target=decision.target,
                reason=decision.reason,
                mode=decision.mode,
                status=status,
                sunny=sunny,
                sunny_source=source,
                room_temp=room_temp,
            )
            if elevation is not None and azimuth is not None:
                sun_now = sun_on_glass(elevation, azimuth, blind.geometry)
                snapshot.sun_on_glass = sun_now.on_glass
                snapshot.profile_angle = sun_now.profile_angle
                snapshot.sunlit_height = sun_now.sunlit_height
            blind.snapshot = snapshot

        self._schedule_save()
        return {blind_id: blind.snapshot for blind_id, blind in self.blinds.items()}

    def _read_cover(self, blind: BlindRuntime) -> tuple[int | None, bool]:
        cover = self.hass.states.get(blind.conf[CONF_COVER])
        if cover is None or cover.state in _NO_VALUE:
            return None, False
        raw = cover.attributes.get("current_position")
        position = int(raw) if raw is not None else None
        return position, cover.state in _MOVING_STATES

    def _track_manual_moves(
        self, blind: BlindRuntime, position: int | None, moving: bool, now: datetime
    ) -> None:
        """Spot a blind that is not where Blind Pilot last left it."""
        state = blind.state
        if position is None:
            # Re-sync when the cover comes back, so a reconnect is not read as a hand move.
            state.expected_position = None
            state.command_time = None
            return
        if state.expected_position is None:
            state.expected_position = position
            return
        in_transit = state.command_time is not None and now - state.command_time < TRANSIT_TIMEOUT
        if moving or in_transit:
            return
        state.command_time = None
        if abs(position - state.expected_position) > POSITION_TOLERANCE:
            previous = state.expected_position
            kind = apply_manual_move(state, previous, position, now, self._hold)
            _LOGGER.info(
                "%s was %s by hand (%s%% to %s%%); holding until %s",
                blind.name,
                kind,
                previous,
                position,
                dt_util.as_local(state.hold_until).strftime("%H:%M"),
            )

    def _move(self, blind: BlindRuntime, target: int, reason: str, now: datetime) -> None:
        _LOGGER.info("Moving %s to %s%%: %s", blind.name, target, reason)
        blind.state.expected_position = target
        blind.state.command_time = now
        blind.state.last_move = now
        self.hass.async_create_task(
            self.hass.services.async_call(
                "cover",
                "set_cover_position",
                {ATTR_ENTITY_ID: blind.conf[CONF_COVER], "position": target},
            )
        )

    async def _async_refresh_forecast(self, now: datetime) -> None:
        """Fetch today's forecast high, which decides the day type."""
        if self._forecast_checked is not None:
            wait = FORECAST_INTERVAL if self._forecast_high is not None else FORECAST_RETRY
            if now - self._forecast_checked < wait:
                return
        self._forecast_checked = now
        weather = self.conf[CONF_WEATHER]
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {ATTR_ENTITY_ID: weather, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("No forecast from %s: %s", weather, err)
            return
        forecast = ((response or {}).get(weather) or {}).get("forecast") or []
        today = dt_util.now().date()
        high = None
        for item in forecast:
            when = dt_util.parse_datetime(str(item.get("datetime")))
            if when is not None and dt_util.as_local(when).date() == today:
                high = item.get("temperature")
                break
        if high is None and forecast:
            high = forecast[0].get("temperature")
        if high is not None:
            self._forecast_high = float(high)

    def _float_state(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _NO_VALUE:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "settings": dict(self.settings),
            "day_high": {"day": self._day_high.day, "value": self._day_high.value},
            "blinds": {
                blind_id: {
                    BLIND_AUTOMATIC: blind.automatic,
                    BLIND_WAIT_FOR_HAND: blind.wait_for_hand,
                    "armed": blind.state.armed,
                    "armed_day": blind.state.armed_day,
                    "hold_until": _format_datetime(blind.state.hold_until),
                    "last_move": _format_datetime(blind.state.last_move),
                }
                for blind_id, blind in self.blinds.items()
            },
        }

    def _schedule_save(self) -> None:
        data = self._data_to_save()
        if data != self._saved:
            self._saved = data
            self._store.async_delay_save(lambda: data, 5)


def _parse_time(value: Any, default: str) -> time:
    return dt_util.parse_time(str(value or default)) or dt_util.parse_time(default)


def _parse_datetime(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
