"""Binary sensors: whether a blind is armed, and whether direct sun is on its glass."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BlindPilotConfigEntry
from .entity import BlindPilotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlindPilotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors."""
    coordinator = entry.runtime_data
    for blind_id in coordinator.blinds:
        async_add_entities(
            [
                ArmedBinarySensor(coordinator, "armed", blind_id),
                SunOnGlassBinarySensor(coordinator, "sun_on_glass", blind_id),
            ],
            config_subentry_id=blind_id,
        )


class ArmedBinarySensor(BlindPilotEntity, BinarySensorEntity):
    """On once the blind has been raised by hand today, or does not need that."""

    _attr_icon = "mdi:hand-back-right"

    @property
    def is_on(self) -> bool:
        """Return whether the blind is armed."""
        return self.blind.state.armed


class SunOnGlassBinarySensor(BlindPilotEntity, BinarySensorEntity):
    """On while the sun is out and its position puts direct sun on this glass."""

    _attr_icon = "mdi:white-balance-sunny"

    @property
    def is_on(self) -> bool:
        """Return whether direct sun reaches the glass."""
        return self.snapshot.sun_on_glass and self.snapshot.sunny is not False
