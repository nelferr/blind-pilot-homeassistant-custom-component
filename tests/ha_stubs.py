"""Minimal stand-ins for the Home Assistant modules the coordinator imports.

They let the coordinator's update loop run under plain unittest. They are not a
substitute for testing inside Home Assistant.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
import enum
import sys
import types

LOCAL = timezone(timedelta(hours=1))  # Lisbon summer time


class Clock:
    """The time the stubbed dt_util reports."""

    now = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)

    @classmethod
    def set_local(cls, hour: int, minute: int = 0) -> None:
        cls.now = datetime(2026, 10, 3, hour, minute, tzinfo=LOCAL).astimezone(timezone.utc)

    @classmethod
    def advance(cls, **kwargs) -> None:
        cls.now += timedelta(**kwargs)


class State:
    def __init__(self, state, attributes=None):
        self.state = str(state)
        self.attributes = attributes or {}


class States:
    def __init__(self):
        self._states: dict[str, State] = {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def set(self, entity_id, state, attributes=None):
        self._states[entity_id] = State(state, attributes)


class Services:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.forecast_high = 22.0

    async def async_call(self, domain, service, data, blocking=False, return_response=False):
        if (domain, service) == ("weather", "get_forecasts"):
            item = {"datetime": Clock.now.isoformat(), "temperature": self.forecast_high}
            return {data["entity_id"]: {"forecast": [item]}}
        self.calls.append((domain, service, dict(data)))
        return None


class FakeHass:
    def __init__(self):
        self.states = States()
        self.services = Services()

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)


class _Generic:
    def __class_getitem__(cls, item):
        return cls


class _Store(_Generic):
    def __init__(self, hass, version, key):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data

    def async_delay_save(self, data_func, delay=0):
        self.data = data_func()


class _DataUpdateCoordinator(_Generic):
    def __init__(self, hass, logger, *, config_entry=None, name=None, update_interval=None):
        self.hass = hass
        self.config_entry = config_entry
        self.data = None

    async def async_refresh(self):
        self.data = await self._async_update_data()

    async_request_refresh = async_refresh
    async_config_entry_first_refresh = async_refresh


class _CoordinatorEntity(_Generic):
    def __init__(self, coordinator):
        self.coordinator = coordinator


def _parse_datetime(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value):
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def install() -> None:
    """Register the stub modules. Safe to call more than once."""
    if "homeassistant" in sys.modules:
        return

    def module(name, **members):
        mod = types.ModuleType(name)
        mod.__dict__.update(members)
        sys.modules[name] = mod
        return mod

    module("homeassistant")
    module("homeassistant.helpers")
    module("homeassistant.util")
    module("homeassistant.config_entries", ConfigEntry=_Generic)
    module(
        "homeassistant.const",
        ATTR_ENTITY_ID="entity_id",
        STATE_ON="on",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
        Platform=enum.Enum("Platform", "BINARY_SENSOR BUTTON NUMBER SENSOR SWITCH"),
    )
    module(
        "homeassistant.core",
        CALLBACK_TYPE=object,
        Event=object,
        HomeAssistant=FakeHass,
        callback=lambda func: func,
    )
    module("homeassistant.exceptions", HomeAssistantError=type("HomeAssistantError", (Exception,), {}))
    module("homeassistant.helpers.event", async_track_state_change_event=lambda *args: lambda: None)
    module("homeassistant.helpers.storage", Store=_Store)
    module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_DataUpdateCoordinator,
        CoordinatorEntity=_CoordinatorEntity,
    )
    module(
        "homeassistant.util.dt",
        utcnow=lambda: Clock.now,
        now=lambda: Clock.now.astimezone(LOCAL),
        as_local=lambda value: value.astimezone(LOCAL),
        parse_datetime=_parse_datetime,
        parse_time=_parse_time,
    )
    sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]
