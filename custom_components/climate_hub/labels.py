"""Source labels of the room readings (docs/integration.md §8.3; R16)."""

from collections.abc import Collection, Sequence

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from .logic.readings import labels, tokens


def entity_name(hass: HomeAssistant, entity_id: str) -> str:
    """The friendly name, else the registry name, else the entity ID."""
    state = hass.states.get(entity_id)
    if state is not None and (name := state.attributes.get("friendly_name")):
        return str(name)
    entry = er.async_get(hass).async_get(entity_id)
    return str((entry and (entry.name or entry.original_name)) or entity_id)


def area_words(hass: HomeAssistant, area_id: str) -> set[str]:
    """Case-folded tokens of the area's name and aliases."""
    area = ar.async_get(hass).async_get_area(area_id)
    if area is None:
        return set()
    return {
        token.casefold()
        for text in (area.name, *area.aliases)
        for token in tokens(text)
    }


def source_labels(
    hass: HomeAssistant,
    area_id: str,
    entity_ids: Sequence[str],
    metric_words: Collection[str],
) -> dict[str, str]:
    """Label per source entity: its name without the room's area and metric words."""
    return labels(
        [(entity_id, entity_name(hass, entity_id)) for entity_id in entity_ids],
        area_words(hass, area_id),
        metric_words,
    )
