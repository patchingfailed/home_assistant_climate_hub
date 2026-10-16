"""Repair issues: source outages, new sources, windows without a room (integration §10).

The coordinator and `async_setup_entry` call these functions; all issue logic lives
here. Fix flows are in `repairs.py`.
"""

from collections.abc import Collection
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, SUBENTRY_REGION, SUBENTRY_ROOM
from .flows.preview import area_name, async_texts, entity_name
from .logic import model as m
from .logic.engine import EngineResult
from .logic.prefill import Scope, new_sources, suggest_sources
from .logic.sources import Metric, Resolution
from .registry import entity_infos
from .store import SeenEntry, fingerprint

if TYPE_CHECKING:
    from .coordinator import ClimateHubConfigEntry, ClimateHubCoordinator

OUTAGE_PREFIX = "outage_"
NEW_SOURCE_PREFIX = "new_source_"
WINDOWS_PREFIX = "windows_without_room_"

_SCOPES = {SUBENTRY_ROOM: Scope.ROOM, SUBENTRY_REGION: Scope.REGION}
_METRICS = (Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE)


def _domain_issues(hass: HomeAssistant, prefix: str) -> set[str]:
    """IDs of this domain's issues that start with `prefix`."""
    return {
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(prefix)
    }


def _delete(hass: HomeAssistant, issue_ids: Collection[str]) -> None:
    for issue_id in issue_ids:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _known_subentry(rest: str, subentry_ids: Collection[str]) -> bool:
    """Whether `<subentry id>_<entity id>` starts with an existing subentry ID."""
    return any(rest.startswith(f"{subentry_id}_") for subentry_id in subentry_ids)


# Setup


@callback
def async_clean_stale(hass: HomeAssistant, entry: ClimateHubConfigEntry) -> None:
    """Delete outage and new-source issues of subentries that no longer exist."""
    ids = set(entry.subentries)
    for prefix in (OUTAGE_PREFIX, NEW_SOURCE_PREFIX):
        _delete(
            hass,
            {
                issue_id
                for issue_id in _domain_issues(hass, prefix)
                if not _known_subentry(issue_id.removeprefix(prefix), ids)
            },
        )


@callback
def async_update_seen(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> None:
    """Record the pre-fillable entities of rooms and regions whose data changed (I4)."""
    infos = None
    changed = False
    for subentry in entry.subentries.values():
        scope = _SCOPES.get(subentry.subentry_type)
        if scope is None:
            continue
        fp = fingerprint(subentry.data)
        seen = coordinator.seen.get(subentry.subentry_id)
        if seen is not None and seen.fingerprint == fp:
            continue
        infos = infos if infos is not None else entity_infos(hass)
        sources = suggest_sources(
            subentry.data[m.CONF_AREA], infos, Metric.TEMPERATURE, scope
        ).sources
        coordinator.seen[subentry.subentry_id] = SeenEntry(fp, tuple(sources))
        changed = True
    if changed:
        coordinator.store.schedule_save(coordinator.store_data)


async def async_sync_windows(
    hass: HomeAssistant, entry: ClimateHubConfigEntry, model: m.HouseModel
) -> None:
    """One issue per area with windows but no room (W11)."""
    texts = await async_texts(hass)
    by_area: dict[str, list[str]] = {}
    for window in model.windows.values():
        if window.room_id is None:
            by_area.setdefault(window.area_id, []).append(
                entry.subentries[window.id].title
            )
    wanted = set()
    for area_id, titles in by_area.items():
        issue_id = f"{WINDOWS_PREFIX}{area_id}"
        wanted.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="windows_without_room",
            translation_placeholders={
                "area": area_name(hass, area_id),
                "windows": texts.join_and(sorted(titles)),
            },
            data={"entry_id": entry.entry_id, "area_id": area_id},
        )
    _delete(hass, _domain_issues(hass, WINDOWS_PREFIX) - wanted)


# New sources (R14)


@callback
def async_sync_new_sources(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> None:
    """One issue per pre-fillable entity that is neither listed nor already seen.

    A dismissed issue stays dismissed: the registry keeps `dismissed_version` when an
    issue is created again.
    """
    infos = entity_infos(hass)
    wanted: set[str] = set()
    for subentry in entry.subentries.values():
        scope = _SCOPES.get(subentry.subentry_type)
        if scope is None:
            continue
        seen = coordinator.seen.get(subentry.subentry_id)
        known = () if seen is None else seen.entities
        area_id = subentry.data[m.CONF_AREA]
        for entity_id in new_sources(
            area_id,
            infos,
            Metric.TEMPERATURE,
            scope,
            listed=subentry.data.get(m.CONF_TEMPERATURE, ()),
            dismissed=(),
        ):
            if entity_id in known:
                continue
            issue_id = f"{NEW_SOURCE_PREFIX}{subentry.subentry_id}_{entity_id}"
            wanted.add(issue_id)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="new_source",
                translation_placeholders={
                    "area": area_name(hass, area_id),
                    "source": entity_name(hass, entity_id),
                    "title": subentry.title,
                },
                data={
                    "entry_id": entry.entry_id,
                    "subentry_id": subentry.subentry_id,
                    "entity_id": entity_id,
                },
            )
    _delete(hass, _domain_issues(hass, NEW_SOURCE_PREFIX) - wanted)


# Outages (H5)


def _resolution(
    result: EngineResult, subentry_id: str, metric: Metric
) -> Resolution | None:
    if (room := result.rooms.get(subentry_id)) is not None:
        return getattr(room, metric.value)
    if (region := result.regions.get(subentry_id)) is not None:
        return getattr(region.own, metric.value)
    return None


async def async_sync_outages(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    model: m.HouseModel,
    result: EngineResult,
) -> None:
    """Create, update and delete the outage issues after an evaluation."""
    if result.house is None or "hub/outages" in result.failures:
        return
    texts = await async_texts(hass)
    hours = f"{model.settings.repair_delay.total_seconds() / 3600:g}"
    wanted: set[str] = set()
    for outage in result.house.outages:
        subentry_id, _, entity_id = outage.entity_id.partition("/")
        subentry = entry.subentries.get(subentry_id)
        if subentry is None:
            continue
        found = None
        for metric in _METRICS:
            resolution = _resolution(result, subentry_id, metric)
            if resolution is not None and any(
                c.entity_id == entity_id for c in resolution.candidates
            ):
                found = (metric, resolution)
                break
        if found is None:
            continue
        metric, resolution = found
        issue_id = f"{OUTAGE_PREFIX}{subentry_id}_{entity_id}"
        wanted.add(issue_id)
        offset = ""
        if resolution.source is None:
            key, active = "outage_none", ""
        else:
            active = entity_name(hass, resolution.source)
            if resolution.offset is not None and round(resolution.offset, 1) != 0:
                key = "outage"
                offset = texts(
                    f"issue_offset_{metric.value}",
                    value=texts.number(resolution.offset, 1, signed=True),
                )
            else:
                key = "outage_fallback"
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={
                "title": subentry.title,
                "source": entity_name(hass, entity_id),
                "hours": hours,
                "active": active,
                "offset": offset,
            },
        )
    # A failed object reports no outages; its issues stay until it evaluates again.
    failed = {key.partition("/")[0] for key in result.failures}
    existing = _domain_issues(hass, OUTAGE_PREFIX)
    wanted.update(
        issue_id
        for issue_id in existing
        if _known_subentry(issue_id.removeprefix(OUTAGE_PREFIX), failed)
    )
    _delete(hass, existing - wanted)


# Removal


@callback
def async_delete_all(hass: HomeAssistant) -> None:
    """Delete every issue of the domain (entry removal)."""
    _delete(hass, _domain_issues(hass, ""))
