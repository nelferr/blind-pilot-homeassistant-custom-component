"""Numbers: the temperatures that decide whether sun is welcome."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import THRESHOLD_SETTINGS
from .coordinator import BlindPilotConfigEntry
from .entity import BlindPilotEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlindPilotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the threshold numbers."""
    coordinator = entry.runtime_data
    async_add_entities(ThresholdNumber(coordinator, key) for key in THRESHOLD_SETTINGS)


class ThresholdNumber(BlindPilotEntity, NumberEntity):
    """One adjustable temperature threshold."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 5
    _attr_native_max_value = 40
    _attr_native_step = 0.5

    @property
    def native_value(self) -> float:
        """Return the threshold."""
        return float(self.coordinator.settings[self._attr_translation_key])

    async def async_set_native_value(self, value: float) -> None:
        """Change the threshold."""
        await self.coordinator.async_set_setting(self._attr_translation_key, value)
