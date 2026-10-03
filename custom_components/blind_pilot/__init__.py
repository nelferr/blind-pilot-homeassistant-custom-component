"""Blind Pilot: sun- and temperature-aware control of interior blinds."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import BlindPilotConfigEntry, BlindPilotCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: BlindPilotConfigEntry) -> bool:
    """Set up Blind Pilot from its config entry."""
    coordinator = BlindPilotCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_start())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Blinds are subentries, so adding or editing one must rebuild everything.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlindPilotConfigEntry) -> bool:
    """Unload Blind Pilot."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_save_now()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: BlindPilotConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
