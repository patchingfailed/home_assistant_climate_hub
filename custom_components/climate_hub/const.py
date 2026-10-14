"""Constants of the Home Assistant adapter (docs/integration.md §6).

Option and subentry data keys live in ``logic/model.py``.
"""

import logging
from datetime import timedelta

from .logic.const import CONTACT_DEBOUNCE

DOMAIN = "climate_hub"
LOGGER = logging.getLogger(__package__)

SUBENTRY_ROOM = "room"
SUBENTRY_REGION = "region"
SUBENTRY_WINDOW = "window"

# Adapter timings (§6)
TICK = timedelta(seconds=60)
REFRESH_COOLDOWN = timedelta(seconds=2)
CONTACT_RECHECK = CONTACT_DEBOUNCE + timedelta(seconds=0.5)
FORECAST_MIN_GAP = timedelta(minutes=15)
FORECAST_BACKSTOP = timedelta(minutes=60)
REGISTRY_DEBOUNCE = timedelta(seconds=5)
RELOAD_DELAY = timedelta(seconds=1)
STORE_SAVE_DELAY = timedelta(seconds=60)

STORE_VERSION = 1
STORE_MINOR_VERSION = 1


def store_key(entry_id: str) -> str:
    """Return the Store key of a hub entry."""
    return f"{DOMAIN}.{entry_id}"
