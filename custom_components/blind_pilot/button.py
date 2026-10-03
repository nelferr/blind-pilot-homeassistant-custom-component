"""Button: hand a blind back to the rules before its manual hold runs out."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BlindPilotConfigEntry
from .entity import BlindPilotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlindPilotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the resume buttons."""
    coordinator = entry.runtime_data
    for blind_id in coordinator.blinds:
        async_add_entities(
            [ResumeButton(coordinator, "resume", blind_id)],
            config_subentry_id=blind_id,
        )


class ResumeButton(BlindPilotEntity, ButtonEntity):
    """Ends the manual hold and arms the blind."""

    _attr_icon = "mdi:play-circle-outline"

    async def async_press(self) -> None:
        """Resume automatic control."""
        await self.coordinator.async_resume(self._blind_id)
