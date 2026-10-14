"""Hub options flow (docs/integration.md 9.6, screen S9).

A plain `OptionsFlow` without `__init__`. The options are stored flat; the section is
UI only. The update listener of the hub entry reloads it.
"""

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from ..logic import model as m
from .common import max_age_selector
from .hub import DEFAULT_TIMING, SECTION_TIMING

_TIMING_KEYS = tuple(DEFAULT_TIMING)


def _number(minimum: int, maximum: int, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def options_schema() -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Optional(m.CONF_WEATHER): EntitySelector(
                EntitySelectorConfig(domain="weather")
            ),
            probatio.Required(m.CONF_AREA_SYNC): BooleanSelector(),
            probatio.Required(SECTION_TIMING): section(
                probatio.Schema(
                    {
                        probatio.Required(m.CONF_MAX_AGE): max_age_selector(),
                        probatio.Required(m.CONF_BURST_DURATION): _number(
                            1, 60, UnitOfTime.MINUTES
                        ),
                        probatio.Required(m.CONF_HUMIDITY_THRESHOLD): _number(
                            30, 90, PERCENTAGE
                        ),
                        probatio.Required(m.CONF_REPAIR_DELAY): _number(
                            1, 72, UnitOfTime.HOURS
                        ),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def flatten_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Form input to the flat options (§3.1)."""
    timing = user_input.get(SECTION_TIMING, {})
    options: dict[str, Any] = {m.CONF_AREA_SYNC: bool(user_input[m.CONF_AREA_SYNC])}
    if weather := user_input.get(m.CONF_WEATHER):
        options[m.CONF_WEATHER] = weather
    for key in _TIMING_KEYS:
        value = timing.get(key, DEFAULT_TIMING[key])
        options[key] = float(value) if key == m.CONF_HUMIDITY_THRESHOLD else int(value)
    return options


def nest_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Stored options to suggested form values."""
    values: dict[str, Any] = {
        m.CONF_AREA_SYNC: options.get(m.CONF_AREA_SYNC, True),
        SECTION_TIMING: {k: options.get(k, DEFAULT_TIMING[k]) for k in _TIMING_KEYS},
    }
    if weather := options.get(m.CONF_WEATHER):
        values[m.CONF_WEATHER] = weather
    return values


class ClimateHubOptionsFlow(OptionsFlow):
    """S9: weather, area sync and the timing section."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=flatten_options(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                options_schema(), nest_options(self.config_entry.options)
            ),
        )
