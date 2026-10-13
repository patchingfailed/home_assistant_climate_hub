# Architecture decisions

One entry per decision: context, decision, consequences. Newest last. Requirement IDs refer to `docs/requirements.md`.

## ADR-001: Native Home Assistant UI first (2026-10-12)

**Context.** Setup and later editing are the riskiest part of the product. Home Assistant offers config flows,
config subentries (one add/edit/delete per object), sections, menus and selectors. A custom sidebar panel would allow
drag-and-drop and live views, but needs its own frontend build, a WebSocket API and upkeep against frontend changes.

**Decision.** Build all management with native flows and subentries. Revisit after the mockups and the first DEV test
(U11). Only if the native UI cannot meet U1–U9 do we move management into a custom panel.

**Consequences.** Lower build and maintenance cost. No live-updating forms: previews are snapshots rendered when a step
opens. The data model must not depend on the UI technology, so a panel can be added later without migration.

## ADR-002: One hub entry with subentries `room`, `region`, `window` (2026-10-12)

**Context.** Rooms, outdoor regions and windows are many similar objects that reference each other. Separate config
entries per object type need ownership rules for house-level entities and break when one type is missing.

**Decision.** Exactly one config entry (`single_config_entry`). Rooms, regions and windows are config subentries of that
entry. House-level settings live in the entry (data for wiring, options for tunables). One coordinator computes all objects.

**Consequences.** Home Assistant renders add/edit/delete per object. House-level entities belong to the hub device and
need no ownership logic. Subentries require a recent Home Assistant (see ADR-004 for the minimum version).

## ADR-003: Regions are HA areas with a compass direction; fallback order is derived (2026-10-12)

**Context.** Configured fallback chains between regions create order dependencies: the first region cannot name a
fallback that does not exist yet, and every later region forces edits on earlier ones.

**Decision.** A region is an outdoor Home Assistant area plus one of N, E, S, W, at most one region per direction.
The fallback order is computed: adjacent directions, then the opposite one, then the weather entity (O3). There is no
fallback setting. Rooms and windows reference a **direction**, which always exists, not a region object.

**Consequences.** Any creation order works (P3, U4). A direction without a region is valid and falls through to its
neighbours or the weather. A preferred ventilation side, if built (O9), is a property of the region, not of the
fallback chain.

## ADR-004: Ranked sources via a sortable entity list, with offset learning (2026-10-12)

**Context.** Sensors in one room differ in quality. Thermostats and air conditioners read with a systematic offset.
Rank dropdowns are clumsy, and multi-select order is invisible unless the selector supports sorting.

**Decision.** Source priority is the order of an entity selector with `multiple` and `reorder` (available since Home
Assistant 2025.9). The highest-ranked valid source wins and takes over again as soon as it is valid. Lower-ranked sources
are corrected by a learned offset relative to the higher-ranked source (rolling window of about 24 h, persisted).
There is no switch hysteresis between sources.

**Consequences.** Minimum Home Assistant version is at least 2025.9; the exact minimum is set together with the
subentry features we use. Learned offsets need persistent storage and must be visible (attributes, diagnostics).
Sorting inside a subentry flow must be verified on DEV before the room form is built.

## ADR-005: Naming (2026-10-12)

**Context.** Entity IDs must be predictable for dashboard templates, but a product abbreviation in every name
("CH Kitchen") is cryptic.

**Decision.** Integration name "Climate Hub", domain `climate_hub`. Device names are translated with placeholders:
rooms and regions "{area} climate" / "{Bereich} Klima", the hub device is "Home climate" / "Hausklima". Windows use
the name the user gives them; left empty, the name is "{area} window" / "{Bereich} Fenster" (numbered from the second
window in a room), stored at creation (amended 2026-10-13: derived compounds such as "Küchenfenster" are not
reliable, the room-based pattern keeps window entity IDs predictable). Entity names come from translation keys.
Unique IDs derive from subentry IDs only.

**Consequences.** Example entity ID on a German instance: `sensor.kuche_klima_temperatur`. Entity IDs are generated once
in the instance language and never change on rename (rule 1). Fused values are distinguishable from raw sensors such as
"Kitchen temperature".

## ADR-006: Tunables that automations may change are entities (2026-10-12)

**Context.** The comfort range is changed by people and by automations (for example a cooler range at night).

**Decision.** Comfort minimum, maximum and threshold are number entities on the hub device, not options-flow fields.
Expert tunables that nobody changes at runtime (maximum age, burst duration, humidity threshold, repair delay) stay in
the hub options.

**Consequences.** Values are restored on restart and can be set from dashboards and automations. Options remain short.
