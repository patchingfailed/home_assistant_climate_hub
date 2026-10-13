"""Logic tests are pure: no Home Assistant instance."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    """Override the root fixture, which needs `hass`."""
    yield
