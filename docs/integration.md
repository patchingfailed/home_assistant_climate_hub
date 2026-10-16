# Integration specification and build plan

Status: **approved 2026-10-14**. Covers the Home Assistant layer around the pure logic of `docs/logic.md`:
manifest, hub entry with subentries, engine, snapshot, coordinator, persistence, devices and entities, flows,
repairs, area sync, translations, diagnostics, tests, and the build order (§15). Requirement IDs refer to
`docs/requirements.md`, ADRs to `docs/architecture.md`, screens to `docs/ui_mockups.md`, logic sections to
`docs/logic.md`. Targets Home Assistant 2026.10 only (ADR-008).

Interfaces below are sketches: names may be refined during the build, semantics may not. Keys marked **frozen** (data
keys, unique IDs, Store keys) cannot change after the first release without a migration (rule 1).

## 0. Decisions

Approved by Felix on 2026-10-14 (I1–I11 in the first round, I12–I17 after the plan review; I16 without objection)
and folded where the last column says.

| # | Topic | Decision | Folded into |
|---|---|---|---|
| I1 | Engine | The eight-step data flow of logic §2 is a pure module `logic/engine.py`. The coordinator only reads Home Assistant, calls the engine, persists and publishes. | ADR-009 |
| I2 | Configuration changes | Every subentry or options change reloads the hub entry. Changes in one burst (S10, repair fixes) give one reload. The comfort numbers do not reload, they re-evaluate. | ADR-009 |
| I3 | Hub settings | All house-level settings live in `entry.options`; `entry.data` stays empty. | ADR-002 |
| I4 | New sources (R14) | Per room and region, the Store remembers which pre-fillable entities were in the area when the object was last saved ("seen"). Only entities that appear afterwards (new or moved in) raise an issue. | R14 |
| I5 | Area sync (R11) | Rooms and outdoor sides. A field is cleared only while it still points to the entity Climate Hub wrote; the previous value is not restored. | R11, S1 |
| I6 | Cover entity (SH2) | Adding a cover later enables the window's „Rollladen" entity if the integration disabled it. Removing the cover leaves the entity as it is. | SH2 |
| I7 | Window-dependent entities | Room entities that need windows and the hub's „Irgendwo …" sensors exist only with windows. Entities the configuration no longer produces are removed from the entity registry. | Mockups §6 |
| I8 | Comfort range | A value that would make minimum ≥ maximum is rejected with a translated error; the old value stays. | H2 |
| I9 | Milestones | Three milestones (§15), one short-lived branch each, merged after green tests and Felix's DEV click review. | §15 |
| I10 | Sun | Sun azimuth and elevation come from `sun.sun`, the standard entity. | §5 |
| I11 | Forecast | Fetched at start, when the weather entity changes (at most every 15 min), and hourly as a backstop. Providers usually update hourly. | §5 |
| I12 | Source-dependent entities | I7 extended by the same rule (no empty shells, rule 4): a room's humidity, absolute humidity, dew point and humidity difference need a humidity source, its pressure a pressure source (own list or followed devices). Room outdoor entities and the hub's outdoor sensor need a region or a weather entity; the strategy needs a weather entity. | §8.3, mockups §6 |
| I13 | Comfort values | Comfort minimum, maximum and threshold are persisted in the Store (not via `RestoreNumber`), so the first evaluation after a start already uses them. | §7 |
| I14 | First evaluation | During Home Assistant start-up the first evaluation waits until Home Assistant has started; entities are unavailable until then (about a minute). Avoids fake fallbacks, outage timers and recommendation flips while source integrations still load. A reload while running evaluates at once. | §6 |
| I15 | Device area | A device follows its subentry's area only when that area changes. A device the user moved by hand stays where it is. | §8.1 |
| I16 | Word lists and preview language | Outside words (S2) and state words (S8d) are comma-separated strings in the `common` section of the translations (the only free section hassfest accepts). Previews are assembled in the instance language, because a flow does not know the user's language. | §12 |
| I17 | S10 preview | Changing or adding an outdoor area in the house plan (S10) suggests sources for it. P1 needs them visible, so S10 gets the regions part of the S4 preview before saving. This is a UI addition (rule 8), approved without a mockup round. | §9.6, mockups S10 |

## 1. Layers and files

```
 flows (config_flow.py, flows/)      repairs.py         diagnostics.py
        │ one-shot engine runs for previews │                  │
        ▼                                   ▼                  ▼
 coordinator.py ── registry.py (model, prefill inputs) ── issues.py, area_sync.py
        │ snapshot.py (states → plain values)    store.py (Store + logic/codec.py)
        ▼
 logic/engine.py (pure) ── logic/model.py (pure config types) ── logic/* modules (built)
        │
        ▼
 entity.py ── sensor.py, binary_sensor.py, number.py
```

```
custom_components/climate_hub/
  __init__.py        setup, unload, remove; coalesced reload; devices; stale-entity cleanup
  manifest.json
  const.py           domain, subentry types, data and option keys, adapter timings (no text)
  registry.py        EntityInfo/AreaInfo snapshots, effective areas, follow resolution, build_model()
  snapshot.py        readings with unit conversion, contacts, climate devices, covers, weather, sun, forecast fetch
  coordinator.py     DataUpdateCoordinator: listeners, tick, debounce, contact re-check, Store, registry listener
  store.py           Store wrapper: load, delayed save, flush, prune
  entity.py          base entity, device helpers, entity descriptions and conditions
  sensor.py, binary_sensor.py, number.py
  issues.py          issue sync: outages (H5), new sources (R14), windows without a room (W11)
  repairs.py         fix flows
  area_sync.py       R11
  diagnostics.py
  config_flow.py     hub flow S1–S4, reconfigure S10, options S9, subentry type registration
  flows/common.py    choice lists, schema builders, validation helpers
  flows/preview.py   markdown previews from one-shot engine results
  flows/room.py, flows/region.py, flows/window.py   subentry flows S6, S7, S8 (window steps as a mixin)
  translations/en.json, translations/de.json
  icons.json
  logic/model.py     pure config types and parsers (new)
  logic/engine.py    pure evaluation (new)
  logic/codec.py     pure JSON codec of the engine state (new)
```

Flow modules never import each other except `flows/common.py`, `flows/preview.py` and the window mixin.

## 2. Manifest

```json
{
  "domain": "climate_hub",
  "name": "Climate Hub",
  "codeowners": [],
  "config_flow": true,
  "dependencies": ["repairs"],
  "after_dependencies": ["recorder", "sun", "weather"],
  "documentation": "https://github.com/<owner>/home_assistant_climate_hub",
  "integration_type": "service",
  "iot_class": "calculated",
  "single_config_entry": true,
  "version": "0.1.0"
}
```

`integration_type` stays `service` as on the DEV spike. `config_flow` becomes `true` in the step that adds the config
flow (§15, step 12). `hacs.json`, brand images and CI belong to the CI task (STATUS Next 3), not to this plan.
`ConfigFlow.VERSION = 1`, `MINOR_VERSION = 1`.

## 3. Configuration model

### 3.1 Entry

`entry.data` is empty (I3). `entry.title` is "Climate Hub". `entry.options` (**frozen** keys):

| Key | Type | Default | Screen |
|---|---|---|---|
| `weather` | entity ID or absent | first weather entity with a forecast | S1, S9 |
| `area_sync` | bool | `true` | S1, S9 |
| `max_age` | int, minutes | 40 (`DEFAULT_MAX_AGE`) | S9 |
| `burst_duration` | int, minutes | 10 | S9 |
| `humidity_threshold` | float, % | 60 | S9 |
| `repair_delay` | int, hours | 6 | S9 |

Form sections are UI only: stored data is flat.

### 3.2 Subentries

Types in this order (S5 ⋮ order): `room`, `region`, `window`. Direction values are the logic's `Direction` values
(`n`, `e`, `s`, `w`), so select translations map them to „Norden" etc.

**Room** (**frozen** keys). Subentry `unique_id` `room_<area_id>`, updated with the area. Title: the area name.

| Key | Type | Meaning |
|---|---|---|
| `area` | area ID | R1 |
| `side` | `n` / `e` / `s` / `w` / `none` | main side (R9) |
| `temperature` | list of entity IDs | ranked sources (R2) |
| `humidity`, `pressure` | list of entity IDs | ranked sources; empty means "follow the temperature devices" (R3) |
| `climate_devices` | list of entity IDs | heating and cooling devices (R15) |
| `max_age` | int minutes or absent | override of the hub value |

**Region** (**frozen** keys). Subentry `unique_id` `region_<direction>`. Title „{direction} · {area}" („Norden ·
Straße"), direction name from translations.

| Key | Type | Meaning |
|---|---|---|
| `area` | area ID | O1 |
| `direction` | `n` / `e` / `s` / `w` | O1, one region per direction |
| `temperature`, `humidity`, `pressure`, `max_age` | as for rooms | O2 |

**Window** (**frozen** keys). No subentry `unique_id` (several per room). Title „{area} {name}" („Küche Fenster").

| Key | Type | Meaning |
|---|---|---|
| `area` | area ID | the room's area (W1); the room subentry may be missing (W11) |
| `type` | `single` / `double` / `pass_through` | S8 |
| `name` | string | stored at creation: the user's name, else „Fenster" / „Durchgang", numbered from the second in the room |
| `leaf` | entity ID | single: the sash contact |
| `leaf_left`, `leaf_right` | entity IDs | double |
| `tilt` | entity ID or absent | single and double: tilt discriminator („Kontakt zwischen den Flügeln" for double) |
| `handle` | entity ID or absent | single and double |
| `inner`, `outer` | entity IDs | pass-through |
| `mappings` | `{entity_id: {closed\|ajar\|tilted\|open: [texts]}}` | text sensors (S8d, W2) |
| `cover` | entity ID or absent | SH2 |
| `facing` | `room` / `n` / `e` / `s` / `w` | default `room` |
| `facing_degrees` | float or absent | SH4 |
| `min_level` | `ajar` / `tilted` / `open` | default `tilted` (W3) |

Subentry titles are set when the object is saved; a renamed area shows on the integration page after the next save.
Device names do not contain the area (ADR-007), so they are not affected.

### 3.3 Pure model (`logic/model.py`)

Frozen dataclasses with no Home Assistant imports, built by `registry.build_model(hass, entry)`:

```python
@dataclass(frozen=True, slots=True)
class Settings:              # from entry.options, converted to timedelta / float
    max_age: timedelta; burst_duration: timedelta; humidity_threshold: float; repair_delay: timedelta

@dataclass(frozen=True, slots=True)
class RoomModel:
    id: str                                  # subentry ID
    area_id: str
    side: Direction | None
    sources: Mapping[Metric, tuple[str, ...]]  # resolved: "follow" already expanded (R3)
    climate_devices: tuple[str, ...]
    max_age: timedelta                       # own override or the hub value
    window_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RegionModel:
    id: str; area_id: str; direction: Direction
    sources: Mapping[Metric, tuple[str, ...]]; max_age: timedelta

@dataclass(frozen=True, slots=True)
class WindowModel:
    id: str; area_id: str
    room_id: str | None                      # None: no room for this area (W11)
    config: WindowConfig                     # FrameConfig or PassThroughConfig (logic §8)
    kinds: Mapping[str, ContactKind]         # binary_sensor → BINARY, else TEXT
    mappings: Mapping[str, Mapping[Level, frozenset[str]]]
    cover: str | None
    direction: Direction | None              # facing resolved: own, else the room's side
    facing_degrees: float | None
    min_level: Level

@dataclass(frozen=True, slots=True)
class HouseModel:
    settings: Settings
    weather: str | None
    rooms: Mapping[str, RoomModel]; regions: Mapping[str, RegionModel]; windows: Mapping[str, WindowModel]
```

`parse_room`, `parse_region`, `parse_window` and `parse_settings` turn plain mappings into these types (pure, table
tested). Follow resolution (R3) needs the registries and stays in `registry.py`: for an empty humidity or pressure list
it calls `prefill.follow_devices` with the current `EntityInfo` list. `HouseModel` supports equality, so the
coordinator can tell whether a registry change altered the resolved model (§6.4).

## 4. Engine (`logic/engine.py`)

Pure, no Home Assistant imports, `now` as a parameter (rule 6).

```python
def evaluate(model: HouseModel, snap: Snapshot, state: EngineState, comfort: Comfort,
             now: datetime) -> tuple[EngineResult, EngineState]
```

### 4.1 Inputs

```python
@dataclass(frozen=True, slots=True)
class Comfort: c_min: float; c_max: float; threshold: float

@dataclass(frozen=True, slots=True)
class Contact: raw: str | None; last_changed: datetime | None

@dataclass(frozen=True, slots=True)
class Forecast: points: tuple[ForecastPoint, ...]; hourly: bool

@dataclass(frozen=True, slots=True)
class Snapshot:
    readings: Mapping[tuple[str, Metric], Reading]   # every source of every list, statuses set by the adapter
    contacts: Mapping[str, Contact]
    climate: Mapping[str, ClimateDevice]             # heating and cooling devices
    covers: Mapping[str, CoverPosition]
    weather: WeatherReadings | None
    clouds: float | None                             # weather attribute cloud_coverage
    forecast: Forecast | None
    sun_azimuth: float | None
    sun_elevation: float | None
```

### 4.2 State (persisted, §7)

```python
@dataclass(frozen=True, slots=True)
class RoomState:
    sources: Mapping[Metric, SourceState]
    trend_state: TrendState
    position: Position | None; relation: Relation | None; dryness: Dryness | None; trend: Trend | None
    goal: GoalState | None

@dataclass(frozen=True, slots=True)
class RegionState: sources: Mapping[Metric, SourceState]

@dataclass(frozen=True, slots=True)
class WindowStore: debounced: Debounced | None; open_since: datetime | None; cover: CoverState | None

@dataclass(frozen=True, slots=True)
class HubState:
    weather_offsets: WeatherOffsets | None; forecast_bias: ForecastBias | None
    strategy: Strategy | None; outages: OutageState | None

@dataclass(frozen=True, slots=True)
class EngineState:
    rooms: Mapping[str, RoomState]; regions: Mapping[str, RegionState]
    windows: Mapping[str, WindowStore]; hub: HubState
```

Every state has a start-up value (`EngineState.empty()`). Objects missing from the state start fresh.

### 4.3 Steps

The order follows logic §2 and the contract in logic §14.

1. **Regions.** Per region and metric: `sources.resolve` with the region's `max_age` and bounds `(0, 100)` for
   humidity, else `None` → `RegionOwn`.
2. **Weather offsets.** `learn_weather_offsets(regions_own, snap.weather, state.hub.weather_offsets, now)`, before any
   `resolve_direction`.
3. **Directions.** `resolve_direction` for each of N, E, S, W and for `None` (rooms without a side). Region results use
   their own direction.
4. **House outdoor.** `house_outdoor(...)`.
5. **Rooms.** Per room: resolve the three metrics; absolute humidity and dew point via `psychro`; outdoor values of
   the room's side; differences outside − inside; `comfort_position`, `outside_relation`, `outside_dryness`, `trend`.
6. **Strategy.** `update_forecast_bias` with the house outdoor value only when its stage is not `weather`, else `None`.
   Then `daily_strategy` with the comfort values and the new bias.
7. **Windows.** Per window: `contact_level` per contact → `window_level` → `debounce(min_level)` → `open_since(min_level,
   startup_hint)`. The start-up hint is the latest `last_changed` of the window's contacts. Then `room_windows` per room.
8. **Recommendation.** Per room: `recommend`, `warnings` and `open_while_conditioning` (only with windows and devices).
   `has_windows` means at least one window; `ventilating` is `None` without windows.
9. **Cover.** Per window: `cover(...)` with the window's direction (`facing_azimuth`), the outdoor temperature of that
   direction, and its room's values. Without a room: `none` / `no_room`. Without a direction and without exact degrees:
   `none` / `no_data`.
10. **House.** `indoor_average`, `any_of` for the warnings and A12, `any_cover_to_close`, and `outages`. The outage key
    is `"<object id>/<entity id>"`. An entity counts as invalid in an object when all its readings there are invalid.
    The status comes from its first metric in the order temperature, humidity, pressure.

### 4.4 Isolation (N2)

Each region, room, window and hub part runs inside its own `try`. A failing object has no result (its entities become
unavailable) and keeps its previous state. Dependants see it as missing data, not as a missing object: for example, a
window of a failed room gets `no_data`, not `no_room`. Failures are returned as `failures: Mapping[str, str]` (object
ID → exception text); the engine does not log.

### 4.5 Result

```python
@dataclass(frozen=True, slots=True)
class RoomResult:
    temperature: Resolution; humidity: Resolution; pressure: Resolution
    absolute_humidity: float | None; dew_point: float | None
    outdoor: OutdoorValues
    temperature_difference: float | None; humidity_difference: float | None
    humidity_after_ventilating: float | None
    position: Position | None; relation: Relation | None; trend: Trend | None
    recommendation: RecommendationResult
    windows: RoomWindows | None
    cooling_down: bool | None; heating_up: bool | None; open_while_conditioning: bool | None

@dataclass(frozen=True, slots=True)
class RegionResult: own: RegionOwn; values: OutdoorValues

@dataclass(frozen=True, slots=True)
class WindowResult: level: WindowLevel; state: WindowState; cover: CoverResult

@dataclass(frozen=True, slots=True)
class HouseResult:
    strategy: StrategyResult; indoor: HouseValue; outdoor: HouseOutdoor
    any_cooling_down: bool | None; any_heating_up: bool | None; any_open_while_conditioning: bool | None
    any_cover_to_close: bool; covers_to_close: tuple[tuple[str, CoverReason], ...]   # window IDs
    outages: tuple[Outage, ...]

@dataclass(frozen=True, slots=True)
class EngineResult:
    rooms: Mapping[str, RoomResult]; regions: Mapping[str, RegionResult]
    windows: Mapping[str, WindowResult]; house: HouseResult | None
    failures: Mapping[str, str]
```

### 4.6 Tests (`tests/logic/test_engine.py`)

Table and scenario tests with hand-built models and snapshots, no `hass`:
- Acceptance scenarios 2, 3, 4, 5, 6, 7, 9, 10, 11, 12 of the requirements, run over several evaluations with
  advancing `now`. Scenario 10: two models built in different subentry orders give equal results.
- The logic §14 contract: weather offsets learned before directions resolve; the bias is fed only off the weather stage;
  the same `min_level` reaches `debounce` and `open_since`; outages are built from candidate statuses.
- Isolation: a model whose room raises (an injected bad mapping) leaves the other rooms, regions and the house intact
  and keeps the failed room's previous state.
- Window without a room: state works, cover `no_room`, no room aggregation.
- Room without windows: recommendation without `keep_*`, warnings `None`.

## 5. Snapshot (`snapshot.py`)

Builds the engine `Snapshot` from `hass.states` for one `HouseModel`. Functions are also used one by one by the flows.

| Input | Rule |
|---|---|
| Sensor reading | `state.state` as float, converted from `unit_of_measurement` with `TemperatureConverter` / `PressureConverter` to °C / hPa; humidity needs `%`. `reported_at = state.last_reported` (R4). Status: no state → `missing`, `unavailable`, `unknown`, not a number → `not_numeric`, unit not convertible → `unit`. |
| `climate` reading | attributes `current_temperature` / `current_humidity` (R5), temperature unit from `hass.config.units`. A missing attribute is `unknown`. Never `temperature` (setpoint). |
| Climate device (A12) | `ClimateDevice(hvac_action=attributes.get("hvac_action"), hvac_mode=state.state)` |
| Contact | `Contact(raw=state.state, last_changed=state.last_changed)`; no state → `raw=None` |
| Cover | `cover.cover_position(state.state, attributes.get("current_position"))` |
| Weather | `WeatherReadings` from attributes `temperature`, `humidity`, `pressure` with `temperature_unit` / `pressure_unit`, `reported_at = last_reported`; `clouds = cloud_coverage` |
| Sun | `sun.sun` attributes `azimuth` and `elevation` (I10); missing entity or attribute → `None` |
| Forecast | cached by the coordinator (§6.3) |

**Forecast fetch** (`async_fetch_forecast(hass, weather_id)`): `weather.get_forecasts` with `type: hourly` if the
entity supports it (`WeatherEntityFeature.FORECAST_HOURLY`), else `daily`, `blocking=True, return_response=True`.
`datetime` → `ForecastPoint.start`, `temperature`, `templow` → `temp_low`, converted from the entity's
`temperature_unit`. Errors are caught: `None` and a debug log line.

Tests (`tests/integration/test_snapshot.py`): every status, unit conversion (°F source, Pa pressure), `last_reported`
on an unchanged value, climate attributes, weather units, the forecast with a registered fake `weather.get_forecasts`
service (hourly, daily-only, failing).

## 6. Coordinator (`coordinator.py`)

`ClimateHubCoordinator(DataUpdateCoordinator[EngineResult])` with `config_entry=entry` and
`update_interval=60 s` (N1). Stored in `entry.runtime_data` (`type ClimateHubConfigEntry = ConfigEntry[ClimateHubData]`
with coordinator, model and store). Adapter timings live in `const.py`:

| Constant | Value | Use |
|---|---|---|
| `TICK` | 60 s | `update_interval`: freshness, trend samples, timers |
| `REFRESH_COOLDOWN` | 2 s | `Debouncer(immediate=True)` for state-change refreshes |
| `CONTACT_RECHECK` | `CONTACT_DEBOUNCE` + 0.5 s | extra refresh after a contact change, so the debounced level publishes |
| `FORECAST_MIN_GAP` / `FORECAST_BACKSTOP` | 15 min / 60 min | I11 |
| `REGISTRY_DEBOUNCE` | 5 s | registry listener |
| `RELOAD_DELAY` | 1 s | coalesced reload (I2) |
| `STORE_SAVE_DELAY` | 60 s | `Store.async_delay_save` |

### 6.1 Lifecycle

- `async_setup_entry`: load the Store, build the model, create devices (§8.1), create the coordinator, forward the
  platforms, remove stale entities (§8.4), register the update listener. The first refresh runs when Home Assistant has
  started (`async_at_started`, I14); until then entities are unavailable. Area sync (§11) runs after the first
  successful refresh.
- Update listener (I2): on the first call it schedules one reload after `RELOAD_DELAY`; further calls before it fires
  are absorbed. Subentry flows use `async_create_entry` / `async_update_and_abort`, never the reload variants
  (`ha-integration-dev` pitfall). The options flow is a plain `OptionsFlow`.
- `async_unload_entry`: unload platforms, cancel timers and listeners, write the Store at once.
- `async_remove_entry`: clear synced area fields (§11), remove the Store, delete the domain's issues.

### 6.2 Evaluation

`_async_update_data`: `now = dt_util.now()`; build the snapshot; `engine.evaluate(...)`; log new failures once per
object (warning with the object title) and recoveries (info); keep the new state; `store.async_delay_save`; sync
outage issues (§10.1); schedule `CONTACT_RECHECK` if any window's raw level differs from its published level. Raise
`UpdateFailed` only if every object failed.

### 6.3 Listeners

- **States:** one `async_track_state_change_event` over every entity the model references: all sources (including
  followed ones), climate devices, contacts, covers, the weather entity and `sun.sun`. A change requests a debounced
  refresh. A weather change also refetches the forecast if the last fetch is older than `FORECAST_MIN_GAP`.
- **Forecast backstop:** `async_track_time_interval` every `FORECAST_BACKSTOP`, plus one fetch before the first
  evaluation.
- **Comfort numbers:** `coordinator.async_set_comfort(...)` validates (I8), saves the Store at once and requests a
  refresh.

### 6.4 Registry listener (N5, R3, R14)

Entity, device and area registry update events, debounced by `REGISTRY_DEBOUNCE`: rebuild the resolved model. If it
differs from the running one (a followed humidity sensor appeared, a source moved), schedule the coalesced reload.
Otherwise run the R14 issue sync (§10.2). Own entities never change the model (`prefill` ignores the own platform), so
the entities a reload creates cannot cause another reload.

Tests (`tests/integration/test_coordinator.py`, freezer plus `async_fire_time_changed`): tick cadence; a burst of
state changes gives few evaluations; a contact change publishes after 5 s without a further state change; the
forecast fetch rules; the first refresh waits for `EVENT_HOMEASSISTANT_STARTED`; a registry change that alters "follow"
reloads once, one that does not alters nothing; isolation logging; three subentry updates in one tick give one reload.

## 7. Persistence (`store.py`, `logic/codec.py`)

One `Store` per entry: key `climate_hub.<entry_id>`, version 1, minor version 1 (**frozen**). Content:

```json
{
  "engine": { "rooms": {}, "regions": {}, "windows": {}, "hub": {} },
  "comfort": { "min": 20.0, "max": 24.0, "threshold": 2.0 },
  "seen": { "<subentry_id>": { "fingerprint": "<hash of subentry data>", "entities": ["sensor.x"] } },
  "area_sync": { "<area_id>": { "temperature": "sensor.x", "humidity": "sensor.y" } },
  "device_areas": { "<subentry_id>": "<area_id>" }
}
```

- `logic/codec.py` (pure) turns `EngineState` into JSON and back: datetimes as ISO 8601 with offset, timedeltas as
  seconds, `StrEnum` by value, `Level` by lower-case name, tuple keys of `WeatherOffsets` as `"n/temperature"`.
- Loading drops objects whose subentry no longer exists and offsets of entities no longer listed (logic §4 rule 7 does
  the same at runtime). An object that fails to decode starts fresh (debug log), so one bad record never blocks the
  others (N2).
- Saving: `async_delay_save` after each evaluation; the Store's own final write covers shutdown; unload saves at once.
  Comfort values save at once (I13).
- Test (`tests/logic/test_codec.py`): a round trip for every state type of logic §14 with non-trivial values;
  unknown IDs pruned; a corrupt object falls back to its start-up value while the others load.

## 8. Devices and entities

### 8.1 Devices

Created in `async_setup_entry` with `device_registry.async_get_or_create` before the platforms load:

| Device | Identifiers | Subentry | Name | Area |
|---|---|---|---|---|
| Hub | `(climate_hub, <entry_id>)` | none | translation `hub`: "Home climate" / „Hausklima" | none, `entry_type=SERVICE` |
| Room | `(climate_hub, <subentry_id>)` | its own | translation `climate`: "Climate" / „Klima" | the room's area |
| Region | same | its own | translation `climate` | the region's area |
| Window | same | its own | `name` from the data | the room's area |

ADR-007 fallback: if `er.async_get(hass).settings.entity_id_parts` is set and lacks the area, rooms and regions use
translation `climate_area` („{area} Klima") and windows `window_area` („{area} {name}").

Placement (I15): a new device gets its area. On later setups the device moves only if the subentry's area differs from
`device_areas` in the Store (the area the integration last placed it in). A window rename updates the device `name`
(never `name_by_user`); entity IDs never change (rule 1).

### 8.2 Unique IDs and entity IDs

Unique IDs (**frozen**): `<subentry_id>_<key>` for room, region and window entities, `<entry_id>_<key>` for hub
entities. Entities are added with `config_subentry_id` of their subentry. All entities: `has_entity_name`,
`translation_key = key`, `CoordinatorEntity`, `PARALLEL_UPDATES = 0`. Entity IDs come from Home Assistant (area +
device name + entity name, in the instance language at creation), for example `sensor.kuche_klima_temperatur`.

### 8.3 Entities

Native values are rounded to two decimals (one for humidity and pressure) so sub-display noise does not write state
rows; `suggested_display_precision` sets what the UI shows. Enum raw states are the logic enum values (window levels
as `closed` / `ajar` / `tilted` / `open`); the UI translates them (E4).

**Room device**

| Key | Platform | Class / unit | Attributes | Exists when (I7, I12) |
|---|---|---|---|---|
| `temperature` | sensor | TEMPERATURE °C, measurement, 1 | `source`, `stage`, `reason`, `offset` | always |
| `humidity` | sensor | HUMIDITY %, measurement, 0 | same | humidity source |
| `pressure` | sensor | ATMOSPHERIC_PRESSURE hPa, measurement, 0 | same | pressure source |
| `absolute_humidity` | sensor | ABSOLUTE_HUMIDITY g/m³, measurement, 1 | – | humidity source |
| `dew_point` | sensor | TEMPERATURE °C, measurement, 1 | – | humidity source |
| `outside_temperature` | sensor | TEMPERATURE °C, measurement, 1 | `stage`, `regions`, `reason`, `offset` | region or weather |
| `outside_humidity` | sensor | HUMIDITY %, measurement, 0 | same | region or weather |
| `temperature_difference` | sensor | TEMPERATURE_DELTA °C, measurement, 1 | – | region or weather |
| `humidity_difference` | sensor | ABSOLUTE_HUMIDITY g/m³, measurement, 1 | `humidity_after_ventilating` (R13) | humidity source and (region or weather) |
| `outside` | sensor | ENUM `Relation` | – | region or weather |
| `comfort` | sensor | ENUM `Position` | – | always |
| `trend` | sensor | ENUM `Trend` | – | always |
| `recommendation` | sensor | ENUM `Recommendation` | `reason` | always |
| `cooling_down`, `heating_up` | binary_sensor | – | – | windows |
| `open_while_conditioning` | binary_sensor | – | – | windows and climate devices |
| `window` | sensor | ENUM levels | – | windows |
| `window_open_since` | sensor | TIMESTAMP | – | windows |

**Region device:** `temperature`, `humidity`, `pressure`, `absolute_humidity`, `dew_point` from the direction's
`OutdoorValues` (so they show neighbour and weather stages too), attributes `source` (own winner), `stage`, `regions`,
`reason`, `offset`. Always present: the weather can stand in.

**Window device**

| Key | Platform | Class | Attributes | Exists when |
|---|---|---|---|---|
| `state` | sensor | ENUM levels | `open_leaves` (double leaf only) | always |
| `open_since` | sensor | TIMESTAMP | – | always |
| `cover` | sensor | ENUM `CoverAdvice` | `reason` | always; enabled by default only with a cover (SH2, I6) |

**Hub device**

| Key | Platform | Class / unit | Attributes | Exists when |
|---|---|---|---|---|
| `comfort_min`, `comfort_max` | number | TEMPERATURE °C, 10–30 / 15–35, step 0.5 | – | always |
| `threshold` | number | TEMPERATURE_DELTA °C, 0.5–10, step 0.5 | – | always |
| `strategy` | sensor | ENUM `Strategy` | `forecast_max`, `forecast_min`, `corrected_max`, `corrected_min`, `bias_max`, `bias_min` | weather |
| `indoor_average` | sensor | TEMPERATURE °C, measurement | `minimum`, `maximum` | a room |
| `outdoor` | sensor | TEMPERATURE °C, measurement | `stage`, `minimum`, `maximum`, `per_region` | region or weather |
| `any_cooling_down`, `any_heating_up` | binary_sensor | – | – | windows |
| `any_open_while_conditioning` | binary_sensor | – | – | a room with windows and climate devices |
| `any_cover_to_close` | binary_sensor | – | `windows`: list of `{entity_id, reason}` (the windows' `cover` sensors) | windows |

Attribute rules (E6): `reason` only when not `primary`, `offset` only on a fallback or weather stage. `offset` and
`per_region` are `_unrecorded_attributes`; the full candidate list lives in diagnostics, never in attributes.
Attribute values `stage`, `reason`, `open_leaves` are translated through `state_attributes`.

### 8.4 Entity lifecycle

- One table of entity descriptions per platform, each with an `exists(model, object)` predicate. The platforms and
  the cleanup use the same predicates.
- An entity is available only while the coordinator has a result for its object (before the first evaluation, and for
  a failed object, it is unavailable).
- Cleanup at setup: entity registry entries of this config entry whose unique ID the current model does not produce
  are removed (I7). History of a returning entity continues because its entity ID is free again.
- Cover entity (I6): with a cover, if the registry entry is `disabled_by=INTEGRATION`, it is enabled.
- Number entities validate (I8) and raise `ServiceValidationError(translation_domain=DOMAIN,
  translation_key="comfort_range_invalid")`.

Tests (`tests/integration/test_entities.py`, German instance): entity IDs as in mockups §6
(`sensor.wohnzimmer_klima_temperatur`, `sensor.kuche_fenster_zustand`, `number.hausklima_wunschtemperatur_max`); the
`entity_id_parts` variant without area; unique IDs; device areas and the move on area change but not after a manual
move; attributes per stage; conditional entities appear and disappear with windows and sources, and the registry is
cleaned; the cover entity enable rule; comfort validation; an English instance gives English names.

## 9. Flows

Follow the approved screens (mockups §2–§5) and the spike idioms (branch `spike/native-ui`, reference only): a second
step ID per description variant („area changed" hint), a real step method for every menu option, sections for
collapsed groups, `suggested_value` instead of `default` for clearable fields, `include_entities` for context filters
(U6) with the chosen entities always included and the filter lifted when it finds nothing.

### 9.1 Shared parts (`flows/common.py`, `flows/preview.py`)

- Choice lists from `registry.entity_infos(hass)`: source candidates per metric and scope (`prefill.classify` not
  `None`), contacts (binary sensors of the contact classes plus text sensors: a non-numeric state without unit and
  device class whose state or `options` name a window position from the S8d word lists; „Alle Kontakte zeigen" lists
  every text sensor; agreed 2026-10-16 after DEV listed SSIDs and app versions), climate devices, candidate areas
  (S2), outdoor area candidates (S3).
- Suggestions: `prefill.suggest_sources`, `suggest_metric_list`, `suggest_climate_devices`, `propose_rooms`.
- **Previews are one-shot engine runs** (I1): the pending change is applied to the model (`build_model` on the edited
  data), a snapshot is read, and `engine.evaluate` runs with the coordinator's current state (learned offsets, trend,
  goals), or with the empty state during the first setup. The forecast comes from the coordinator's cache, or is
  fetched once during the first setup. `flows/preview.py` turns the result into markdown from translated fragments
  (§12).

### 9.2 First setup (`config_flow.py`, S1–S4)

| Step | Screen | Fields / options | Errors |
|---|---|---|---|
| `user` | S1 | `weather` (entity selector, domain weather, suggested: first with a forecast), `area_sync` (default on); scan counts as placeholders | – |
| `rooms` | S2 | `rooms`: select, multiple, list mode, labels „{floor} · {area}", pre-checked by `propose_rooms` | `no_rooms` |
| `plan` | S3 | sections `n`, `e`, `s`, `w`, each `outdoor` (select, optional) and `rooms` (select, multiple) | `room_two_sides`, `outdoor_twice` |
| `preview` | S4 | menu `create`, `add_window`, `rooms`, `plan` | – |

`create` calls `async_create_entry(title="Climate Hub", data={}, options=..., subentries=[...],
description="created")` with the rooms (suggested sources, side from the plan), the regions (suggested sources, scope
region) and the windows added via `add_window` (window mixin, §9.5; M2).

### 9.3 Room (`flows/room.py`, S6)

`user` (area, add only; errors `already_room`, `is_region`) → `room_form` / `room_form_changed` (fields `area`,
`side`, `temperature`; sections `humidity_pressure`, `climate` expanded on add and collapsed on edit, `advanced` with
`max_age`; error `no_temperature`) → `room_preview` (menu `room_save`, `room_adjust`). `reconfigure` opens the form
directly. Save: `async_create_entry(title, data, unique_id)` or `async_update_and_abort(entry, subentry, title=...,
data=..., unique_id=...)`. When the sources were just suggested, the preview lists what was not taken and why.

### 9.4 Region (`flows/region.py`, S7)

`user` (`direction` from the free directions, `area`) → `region_form` / `region_form_changed` → `region_preview`
(names the fallback chain from `outdoor.fallback_chain`). Errors `direction_taken`, `already_region`, `is_room`,
`no_temperature`.

### 9.5 Window (`flows/window.py`, S8, M2)

Mixin used by the window subentry flow and by the first setup:
`user` (room area, add only; error `is_region`) → `window_type` (menu `window_single`, `window_double`,
`window_pass_through`, with option descriptions) → type form (fields per §3.2, `show_all` toggle re-opens the form with
all contacts, a room change re-opens it with that room's contacts) → `window_mapping` once per chosen text sensor (four
select fields `closed`, `ajar`, `tilted`, `open`, `multiple` + `custom_value`; options are the known texts from the
`options` attribute, recorder history of the last 14 days and the current state; pre-filled by
`window.suggest_text_mapping` with the instance-language and English words) → `window_preview` (menu `window_save`,
`window_adjust`, `window_retype`). If the area has no room yet, the preview says so and saving also adds the room
subentry with suggested sources (U4, `async_add_subentry`). Errors `no_contact`, `same_contact` (one contact in two
roles of one window).

### 9.6 Options and house plan

- **Options (S9):** plain `OptionsFlow` (no custom `__init__`): `weather`, `area_sync`, section `timing` with
  `max_age`, `burst_duration`, `humidity_threshold`, `repair_delay` (number selectors with units). The update listener
  reloads.
- **House plan (S10):** `reconfigure` on the hub entry shows the S3 form filled from the room and region subentries.
  On submit it updates the rooms' `side`, and creates, updates or removes regions. If an outdoor area changed or was
  added, a `plan_preview` step shows the suggested sources of those sides first (I17). Then
  `async_abort(reason="reconfigure_successful")`; the coalesced reload applies everything once.

### 9.7 Tests (`tests/flows/`)

Through the flow manager only (rule 7), on a fixture house (§14): every step and error of S1–S4, S6–S10; the
area-change re-open; the S8d mapping with history; the room created from the window flow; S10 with an added, a changed
and a removed side; `single_config_entry` abort; preview placeholders contain the expected values; the saved data
match §3 exactly.

## 10. Repairs (`issues.py`, `repairs.py`)

Issue IDs (**frozen** prefixes):

| Issue | ID | Fixable | Created / deleted |
|---|---|---|---|
| Source outage (H5) | `outage_<subentry_id>_<entity_id>` | no | from `HouseResult.outages` after each evaluation; deleted when the outage ends |
| New source (R14) | `new_source_<subentry_id>_<entity_id>` | yes | registry listener and setup (I4) |
| Windows without a room (W11) | `windows_without_room_<area_id>` | yes | setup (subentry changes reload) |

All issues: severity warning, not persistent (they are re-synced at setup; Home Assistant keeps an ignored issue's
`dismissed_version` across restarts). Titles name the object as „Sensor für {title}" or the area as „im Bereich
{area}", because a placeholder cannot inflect („im Bad", „in der Küche"). Fixable issues carry their S11 text in the
fix flow's first step (hassfest allows `description` or `fix_flow`, not both).

### 10.1 Outages (H5)

Placeholders: object title, source name, repair delay in hours, active source and applied offset („Für Bad gilt
gerade Thermostat Bad, korrigiert um −0,8 °C"). The metric is the first of temperature, humidity, pressure whose
candidates contain the entity. Three translation keys, chosen at each sync: `outage` (another source is active with
an offset that rounds to non-zero), `outage_fallback` (active source without offset) and `outage_none` (no valid
value). Synced after each evaluation that produced a house result.

### 10.2 New sources (R14, I4)

- **Seen set:** at setup, for each room and region whose `fingerprint` (hash of its subentry data) differs from the
  Store, `seen` becomes every pre-fillable temperature candidate of its area right now. A saved form therefore counts
  as reviewed, including sources the user removed on purpose.
- An issue is raised for each entity from `prefill.new_sources(area, infos, temperature, scope, listed, dismissed)`
  that is not in `seen`. `dismissed` are this domain's `new_source_*` issues the user ignored (`dismissed_version`
  set); such issues are never deleted while the entity qualifies, so "Ignorieren" stays in force. "Pre-fillable"
  includes the R6 last resort: an entity without a device or a helper raises the issue only in an area that has
  nothing better (agreed 2026-10-16; field use will show whether it nags).
- Fix flow: confirm (S11 text) → append the entity to the temperature list; where the humidity or pressure list is
  explicit (not "follow"), the device's matching sensors are appended there too. The issue disappears with the
  reload. Before saving, the fix flow adds only its entity to `seen` and stores the new fingerprint, so other open
  `new_source_*` issues of the same object survive the reload (a fix is not a review of the whole form).

### 10.3 Windows without a room (W11)

Fix flow menu `recreate_room` (shows the S6 preview with suggested sources, then adds the room subentry) and
`delete_windows` (a confirm step naming the windows, then removes the window subentries of that area). The menu
labels carry no placeholders; the menu text names the area and the windows.

Tests (`tests/integration/test_issues.py`, `tests/flows/test_repairs.py`): outage after the delay and its removal;
R14 not raised for a deliberately removed suggestion, raised for a new entity and for one moved into the area, not
raised again after "ignore"; both fix flows end to end; issues removed with the entry.

## 11. Area sync (`area_sync.py`, R11, I5)

- Wanted: for every room and region while `area_sync` is on, the area's `temperature_entity_id` is the object's
  `temperature` entity and `humidity_entity_id` its `humidity` entity (if that exists). Entity IDs come from the
  entity registry by unique ID.
- Runs after the first successful evaluation (Home Assistant rejects an entity that has no state yet or the wrong
  device class) and on every setup. `ValueError` from the registry is logged at debug level.
- Written values are recorded in the Store (`area_sync`). A recorded field that is no longer wanted (sync off, object
  deleted, entity gone) is cleared only if it still holds the recorded entity ID. `async_remove_entry` clears all
  recorded fields under the same rule. The previous value is not restored.
- A field the user changed after Climate Hub wrote it (another sensor, or emptied) is left alone from then on, so one
  area can opt out without switching the sync off. A field never written by Climate Hub is taken over once (the S1
  confirmation covers that).

Tests (`tests/integration/test_area_sync.py`): written on setup; cleared on sync off, room delete and entry removal;
a field the user changed is left alone; regions included.

## 12. Translations

- `translations/en.json` and `de.json` with the same keys (UTF-8, real umlauts). German texts are the approved mockup
  texts; English texts follow them. No first person (copy rule).
- Sections used: `config` (steps, sections, errors, aborts, `create_entry.created`), `config_subentries` (room,
  region, window: steps, errors, menu options with descriptions), `options`, `selector` (side, direction, facing,
  min_level), `entity` (names, enum states, `state_attributes`), `device` (`hub`, `climate`, `climate_area`,
  `window_area`), `issues` (texts and fix flows), `exceptions` (`comfort_range_invalid`), `common` (I16).
- `common` holds the word lists (`outside_words`, `words_closed`, `words_ajar`, `words_tilted`, `words_open`, as
  comma-separated strings), the default window names (`window_name`, `pass_through_name`), direction names for titles,
  `no_floor` („ohne Stockwerk"), and the preview fragments. Python loads them with
  `translation.async_get_translations(hass, hass.config.language, "common", {DOMAIN})`; word lists merge the instance
  language with English.
- Test (`tests/test_translations.py`): both files have the same key set; every `translation_key`, step ID, error,
  issue and `common` key used in code exists; every enum value of the logic that reaches a state or attribute has a
  translation.

## 13. Diagnostics (`diagnostics.py`)

`async_get_config_entry_diagnostics`: options, subentries, the resolved model, the engine state (codec form), the last
result per object including every candidate with status, raw value and learned offset (E6), current failures, the
forecast cache and the Store's bookkeeping (`seen`, `area_sync`, `device_areas`). Nothing to redact (no secrets).
Test: snapshot of the structure on the fixture house.

## 14. Testing

| Layer | Folder | Tools |
|---|---|---|
| Pure logic, model, engine, codec | `tests/logic/` | plain pytest, table cases, no `hass`; the purity test covers the new modules |
| Adapter | `tests/integration/` | `hass` fixture, `MockConfigEntry` with `subentries_data`, freezer, `async_fire_time_changed` |
| Flows and fix flows | `tests/flows/` | flow manager only (rule 7) |

- **Fixture house** (`tests/house.py` plus a `house` fixture): floors, areas, devices and entities shaped like the
  acceptance scenarios: a room with climate sensor and thermostat; a kitchen with fridge, printer and contact
  temperature (scenario 1); a room without humidity; two outdoor areas plus one on a floor without a region; binary
  and text contacts, some without an area (scenario 8); a cover; a weather entity with a registered fake
  `weather.get_forecasts`; `sun.sun`. Generic names only (rule 13). German instance by default, one English case.
- Windows: `python -m pytest` (loads `win_compat`), socket fix in `tests/conftest.py`.
- A step is done when its named tests and the whole suite pass, `ruff check .` and `ruff format --check .` are clean.

## 15. Build order

Each step is one Sonnet implementer brief (`dev-workflow:orchestrate` format). The main session writes the brief from
this plan; a verifier runs the suite after each step. Every step adds its own translations (en and de). A step does not
start before the previous one is green.

### Milestone M1: rooms and outdoor sides (branch `build/m1-rooms`)

| # | Step | Files | Tests | Done when |
|---|---|---|---|---|
| 1 | Package skeleton | `manifest.json` (without `config_flow`), `const.py`, `__init__.py` (setup, unload, remove, runtime data, coalesced reload), translation skeleton | `tests/integration/test_setup.py`: entry with subentries loads and unloads; three subentry updates give one reload | suite green |
| 2 | Model and engine, part 1 | `logic/model.py`, `logic/engine.py`: regions, weather offsets, directions, house outdoor, rooms, strategy, recommendation (without windows), house values, outages, isolation | `tests/logic/test_model.py`, `test_engine.py`: scenarios 2, 3, 4, 11, 12, contract, isolation | suite green, purity test covers the new modules |
| 3 | Engine, part 2 | `logic/engine.py`: windows, room aggregation, warnings, A12, cover, any-flags | `test_engine.py`: scenarios 5, 6, 7, 9, 10, no room, no windows | suite green |
| 4 | Persistence | `logic/codec.py`, `store.py` | `tests/logic/test_codec.py`, Store load and save in `test_setup.py` | suite green |
| 5 | Registries and model building | `registry.py` (`EntityInfo`/`AreaInfo`, effective area, follow, `build_model`) | `tests/integration/test_registry.py` with the fixture house (`tests/house.py`) | suite green |
| 6 | Snapshot and forecast | `snapshot.py` | `tests/integration/test_snapshot.py` | suite green |
| 7 | Coordinator | `coordinator.py`, wiring in `__init__.py` | `tests/integration/test_coordinator.py` (§6) | suite green |
| 8 | Devices and entities without windows | `entity.py`, `sensor.py`, `number.py`; device creation and cleanup in `__init__.py` | `tests/integration/test_entities.py` (room, region, hub parts) | entity IDs as in mockups §6 on a German instance |
| 9 | Diagnostics | `diagnostics.py` | `tests/integration/test_diagnostics.py` | suite green |
| 10 | Area sync | `area_sync.py` | `tests/integration/test_area_sync.py` | suite green |
| 11 | Room and region flows | `flows/common.py`, `flows/preview.py`, `flows/room.py`, `flows/region.py` | `tests/flows/test_room_flow.py`, `test_region_flow.py` | every S6 and S7 path tested |
| 12 | First setup, options, house plan | `config_flow.py` (S1–S4 without `add_window`, S9, S10 with I17), `manifest.json` `config_flow: true` | `tests/flows/test_config_flow.py`, `test_options_flow.py`, `test_reconfigure.py`, `tests/test_translations.py` | suite green |
| 13 | M1 on DEV | none (fixes only) | full suite | spike folder removed from DEV first (STATUS Next 4), deployed with `-Restart`; smoke test of the project skill passes for rooms and regions; Felix's click review; merge |

Step 8 note: `binary_sensor.py` arrives in M2, because M1 has no binary sensor (all of them need windows).

### Milestone M2: windows (branch `build/m2-windows`)

| # | Step | Files | Tests | Done when |
|---|---|---|---|---|
| 14 | Window entities | `binary_sensor.py`, window and room-window descriptions in `sensor.py`, hub any-flags, cover enable rule | `test_entities.py` (window parts, I6, I7 cleanup) | suite green |
| 15 | Window flow | `flows/window.py` (S8, S8a–c, S8d, preview, room creation), window subentry type | `tests/flows/test_window_flow.py` | scenarios 5–8 configurable through the flow |
| 16 | Windows in the first setup | `config_flow.py`: `add_window` loop and the windows part of S4 | `test_config_flow.py` | suite green |
| 16a | Weather status | S4 status line and the S9 check step (mockups S4, S9, agreed 2026-10-15): current values plus one test fetch of the forecast | `test_config_flow.py`, `test_options_flow.py` | mirrored, unavailable and missing weather each show their line |
| 17 | M2 on DEV | fixes only | full suite | click review of the window flow and states with real contacts; merge |

### Milestone M3: repairs (branch `build/m3-repairs`)

| # | Step | Files | Tests | Done when |
|---|---|---|---|---|
| 18 | Issue sync | `issues.py` (H5, R14 with the seen set, W11), hooks in the coordinator | `tests/integration/test_issues.py` | suite green |
| 19 | Fix flows | `repairs.py` | `tests/flows/test_repairs.py` | both fix flows end to end |
| 20 | M3 on DEV | fixes only | full suite | outage by a state-only test sensor set to `unavailable` (delay 1 h in options; DEV's mirrored sensors also go stale on their own), a mirrored entity moved into a room's area, a room deleted next to its window; merge |

After M3: CI (STATUS Next 3).

## 16. Not in this plan

CI, `hacs.json`, brand images and releases (STATUS Next 3). The deferred requirements of logic §14 (A7–A11, R12, O8–O10,
SH3). A custom panel (ADR-001).
