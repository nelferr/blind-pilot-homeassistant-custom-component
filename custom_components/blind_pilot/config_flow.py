"""Setup screens for Blind Pilot: one hub entry, plus one subentry per blind."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
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
    CONF_NAME,
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
    DEFAULT_START,
    DEFAULT_THROTTLE_SOC,
    DOMAIN,
    SUBENTRY_BLIND,
)


def _entity(domain: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


HUB_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_WEATHER): _entity("weather"),
        vol.Optional(CONF_OUTDOOR_TEMP): _entity("sensor"),
        vol.Optional(CONF_LUX): _entity("sensor"),
        vol.Required(CONF_LUX_SUNNY, default=DEFAULT_LUX_SUNNY): _number(1000, 120000, 1000, "lx"),
        vol.Optional(CONF_BATTERY_SOC): _entity("sensor"),
        vol.Required(CONF_THROTTLE_SOC, default=DEFAULT_THROTTLE_SOC): _number(50, 100, 1, "%"),
        vol.Required(CONF_START, default=DEFAULT_START): selector.TimeSelector(),
        vol.Required(CONF_END, default=DEFAULT_END): selector.TimeSelector(),
        vol.Required(CONF_HOLD_HOURS, default=DEFAULT_HOLD_HOURS): _number(0.5, 12, 0.5, "h"),
        vol.Required(CONF_MIN_MOVE, default=DEFAULT_MIN_MOVE): _number(5, 50, 1, "%"),
        vol.Required(CONF_MIN_INTERVAL, default=DEFAULT_MIN_INTERVAL): _number(1, 60, 1, "min"),
    }
)

BLIND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_COVER): _entity("cover"),
        vol.Required(CONF_AZIMUTH): _number(0, 359, 1, "°"),
        vol.Required(CONF_GLASS_HEIGHT, default=2.4): _number(0.3, 6, 0.05, "m"),
        vol.Required(CONF_OVERHANG, default=0): _number(0, 6, 0.05, "m"),
        vol.Required(CONF_LIMIT_GLARE, default=True): selector.BooleanSelector(),
        vol.Required(CONF_PATCH_DEPTH, default=1): _number(0.1, 6, 0.1, "m"),
        vol.Required(CONF_MIN_POSITION, default=15): _number(0, 90, 1, "%"),
        vol.Required(CONF_DUSK_LOWER, default=True): selector.BooleanSelector(),
        vol.Required(CONF_WAIT_FOR_HAND, default=True): selector.BooleanSelector(),
        vol.Optional(CONF_ROOM_TEMP): _entity("sensor"),
        vol.Optional(CONF_DOOR): _entity("binary_sensor"),
        vol.Optional(CONF_PV): _entity("sensor"),
        vol.Required(CONF_PV_PEAK, default=2800): _number(100, 20000, 50, "W"),
        vol.Required(CONF_PV_AZIMUTH, default=180): _number(0, 359, 1, "°"),
        vol.Required(CONF_PV_TILT, default=25): _number(0, 90, 1, "°"),
    }
)


class BlindPilotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single Blind Pilot hub entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the shared inputs: weather, sun sources and active hours."""
        if user_input is not None:
            return self.async_create_entry(title="Blind Pilot", data=user_input)
        return self.async_show_form(step_id="user", data_schema=HUB_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BlindPilotOptionsFlow:
        """Return the options flow."""
        return BlindPilotOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Blinds are added as subentries of the hub."""
        return {SUBENTRY_BLIND: BlindSubentryFlow}


class BlindPilotOptionsFlow(OptionsFlow):
    """Edit the shared inputs."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the hub form again, filled with the current values."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options or self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(HUB_SCHEMA, current),
        )


class BlindSubentryFlow(ConfigSubentryFlow):
    """Add or edit one blind."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a blind."""
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=BLIND_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a blind."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data=user_input,
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(BLIND_SCHEMA, subentry.data),
        )
