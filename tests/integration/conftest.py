"""Fixtures for the integration tests."""

from collections.abc import AsyncIterator

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import (
    mock_config_flow,
    mock_platform,
)

from custom_components.climate_hub.const import DOMAIN


class _StubConfigFlow(config_entries.ConfigFlow):
    """Stand-in flow handler."""


@pytest.fixture(autouse=True)
async def config_flow_platform(hass: HomeAssistant) -> AsyncIterator[None]:
    """Stand in for config_flow.py, which Home Assistant requires to set up an entry.

    Remove with build step 12, which adds the real config flow.
    """
    await async_get_integration(hass, DOMAIN)
    mock_platform(hass, f"{DOMAIN}.config_flow")
    with mock_config_flow(DOMAIN, _StubConfigFlow):
        yield
