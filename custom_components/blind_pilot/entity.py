"""Base entity for Blind Pilot."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BlindPilotCoordinator, BlindRuntime, BlindSnapshot


class BlindPilotEntity(CoordinatorEntity[BlindPilotCoordinator]):
    """An entity on the hub device, or on one blind's device when blind_id is given."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BlindPilotCoordinator, key: str, blind_id: str | None = None
    ) -> None:
        super().__init__(coordinator)
        self._blind_id = blind_id
        self._attr_translation_key = key
        entry_id = coordinator.config_entry.entry_id
        if blind_id is None:
            self._attr_unique_id = f"{entry_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry_id)},
                name="Blind Pilot",
                manufacturer="nelferr",
                entry_type=DeviceEntryType.SERVICE,
            )
        else:
            self._attr_unique_id = f"{blind_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, blind_id)},
                name=coordinator.blinds[blind_id].name,
                manufacturer="nelferr",
                entry_type=DeviceEntryType.SERVICE,
            )

    @property
    def blind(self) -> BlindRuntime:
        """The blind this entity belongs to."""
        return self.coordinator.blinds[self._blind_id]

    @property
    def snapshot(self) -> BlindSnapshot:
        """The latest computed values for this entity's blind."""
        return self.blind.snapshot
