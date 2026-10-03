"""Sensors: each blind's target and status, and the hub's day type."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BlindPilotConfigEntry
from .engine import (
    DAY_COOL,
    DAY_HOT,
    DAY_MILD,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_DOOR_OPEN,
    STATUS_HOLD,
    STATUS_OBSERVING,
    STATUS_OUTSIDE_HOURS,
    STATUS_UNAVAILABLE,
    STATUS_WAITING,
)
from .entity import BlindPilotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlindPilotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors."""
    coordinator = entry.runtime_data
    async_add_entities([DayTypeSensor(coordinator, "day_type")])
    for blind_id in coordinator.blinds:
        async_add_entities(
            [
                TargetSensor(coordinator, "target", blind_id),
                StatusSensor(coordinator, "status", blind_id),
            ],
            config_subentry_id=blind_id,
        )


class TargetSensor(BlindPilotEntity, SensorEntity):
    """The position the rules want, with the reason as an attribute."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:blinds-horizontal"

    @property
    def native_value(self) -> int | None:
        """Return the wanted position; "leave it" shows the current position."""
        snapshot = self.snapshot
        return snapshot.target if snapshot.target is not None else snapshot.position

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Explain the target."""
        snapshot = self.snapshot
        return {
            "reason": snapshot.reason,
            "mode": snapshot.mode,
            "sunny": snapshot.sunny,
            "sunny_source": snapshot.sunny_source,
            "profile_angle": _rounded(snapshot.profile_angle, 1),
            "sunlit_height": _rounded(snapshot.sunlit_height, 2),
            "room_temperature": snapshot.room_temp,
        }


class StatusSensor(BlindPilotEntity, SensorEntity):
    """Whether the blind may be moved right now, and if not, why."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        STATUS_ACTIVE,
        STATUS_OBSERVING,
        STATUS_HOLD,
        STATUS_WAITING,
        STATUS_OUTSIDE_HOURS,
        STATUS_DOOR_OPEN,
        STATUS_DISABLED,
        STATUS_UNAVAILABLE,
    ]

    @property
    def native_value(self) -> str:
        """Return the control status."""
        return self.snapshot.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show when a manual hold ends."""
        hold_until = self.blind.state.hold_until
        if hold_until is not None and hold_until <= dt_util.utcnow():
            hold_until = None
        return {"hold_until": hold_until.isoformat() if hold_until else None}


class DayTypeSensor(BlindPilotEntity, SensorEntity):
    """Cool, mild or hot, from today's expected high."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [DAY_COOL, DAY_MILD, DAY_HOT]

    @property
    def native_value(self) -> str:
        """Return the day type."""
        return self.coordinator.day

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Show the temperature the day type came from."""
        return {"expected_high": self.coordinator.day_high}


def _rounded(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None
