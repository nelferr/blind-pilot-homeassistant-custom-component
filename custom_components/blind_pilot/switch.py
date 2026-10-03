"""Switches: hub-wide modes and per-blind options."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    BLIND_AUTOMATIC,
    BLIND_WAIT_FOR_HAND,
    SETTING_ENERGY_SAVER,
    SETTING_OBSERVE_ONLY,
)
from .coordinator import BlindPilotConfigEntry, BlindPilotCoordinator
from .entity import BlindPilotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlindPilotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SettingSwitch(coordinator, SETTING_OBSERVE_ONLY),
            SettingSwitch(coordinator, SETTING_ENERGY_SAVER),
        ]
    )
    for blind_id in coordinator.blinds:
        async_add_entities(
            [
                BlindSwitch(coordinator, BLIND_AUTOMATIC, blind_id),
                BlindSwitch(coordinator, BLIND_WAIT_FOR_HAND, blind_id),
            ],
            config_subentry_id=blind_id,
        )


class SettingSwitch(BlindPilotEntity, SwitchEntity):
    """A hub-wide mode: observe only, or energy saver."""

    @property
    def is_on(self) -> bool:
        """Return whether the mode is on."""
        return bool(self.coordinator.settings[self._attr_translation_key])

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the mode on."""
        await self.coordinator.async_set_setting(self._attr_translation_key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the mode off."""
        await self.coordinator.async_set_setting(self._attr_translation_key, False)


class BlindSwitch(BlindPilotEntity, SwitchEntity):
    """A per-blind option: automatic control, or waiting for a hand-open."""

    def __init__(self, coordinator: BlindPilotCoordinator, key: str, blind_id: str) -> None:
        super().__init__(coordinator, key, blind_id)
        if key == BLIND_WAIT_FOR_HAND:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        """Return whether the option is on."""
        if self._attr_translation_key == BLIND_AUTOMATIC:
            return self.blind.automatic
        return self.blind.wait_for_hand

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the option on."""
        await self.coordinator.async_set_blind_flag(
            self._blind_id, self._attr_translation_key, True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the option off."""
        await self.coordinator.async_set_blind_flag(
            self._blind_id, self._attr_translation_key, False
        )
