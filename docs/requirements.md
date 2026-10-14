# Climate Hub: Requirements

Status: **draft**, 2026-10-12. Priorities use MoSCoW: **M**ust, **S**hould, **C**ould.
Architecture decisions that follow from these requirements go into `docs/architecture.md` as ADRs.
Screens and texts go into `docs/ui_mockups.md` and need approval before they are built.

## 1. Purpose

A house has many temperature and humidity sensors of uneven quality. Some sit next to a radiator, some report
the fridge, some drop off the network for hours. Climate Hub turns them into **one trustworthy climate picture**:

- **per room:** one temperature, humidity and pressure value from a ranked list of sources, with fallbacks;
- **per outdoor side:** the same, with automatic fallback to neighbouring sides and the weather service;
- **per window:** the window as the bridge between a room and the outside. It reports the opening state and says
  whether opening or closing helps today.

Everything plugs into Home Assistant's own concepts (areas, floors, area sensors, dashboards, automations) instead of
living next to them.

## 2. Audience and product principles

**Audience:** smart-home enthusiasts who are comfortable with Home Assistant. They want control and transparency,
but they do not want to wade through settings.

| # | Principle |
|---|---|
| P1 | **Suggest, never guess silently.** Discovery proposes sources and objects; the user confirms. Nothing becomes a source without being visible in a form. |
| P2 | **One object, one form.** Rooms, outdoor regions and windows are edited one at a time. Every value set during creation stays editable later, including values that are empty. |
| P3 | **No creation-order dependencies.** References point only to things that always exist (Home Assistant areas, compass directions). Any creation order leads to the same result. |
| P4 | **Settings are the last resort.** Prefer a smart default. If the user needs control, prefer an entity (number, switch) that automations can also change. Expert values go into collapsed sections. |
| P5 | **Transparent.** Every value says which source it came from, which fallback stage was used and why. |
| P6 | **Native first.** Use Home Assistant's own flows, selectors, areas, repairs and translations. A custom panel is only built if the native UI cannot be made good enough (see U11). |
| P7 | **Predictable entities.** One dashboard template or popup must work for every room without copy and paste. |

## 3. Concepts

| Term | Meaning |
|---|---|
| **Hub** | The single Climate Hub entry. Holds house-wide settings and house-wide outputs. |
| **Room** | An indoor Home Assistant area that Climate Hub manages. One room per area. |
| **Outdoor region** | An outdoor Home Assistant area (typically on an "outside" floor) with a compass direction (N, E, S, W). Example: "Street" = North, "Yard" = West, "Garden" = South. A side without an outdoor space (shared wall) simply has no region. |
| **Window** | Any opening to the outside that matters for ventilation: window, French or terrace door, exterior door, sliding door. Belongs to a room and faces a region. |
| **Source** | An entity that delivers a measurement: a sensor with a matching device class, or a `climate` entity (current temperature only). |
| **Stage** | Where a value came from: `primary`, `fallback` (lower-ranked source), `neighbour` (adjacent region), `opposite` (opposite region), `weather`, `none`. |
| **Comfort range** | Global desired indoor temperature range (minimum, maximum) plus a threshold used for the daily strategy. |
| **Daily strategy** | House-wide classification of today from the weather forecast: *prevent heat-up*, *prevent cool-down* or *neutral*. |
| **Burst ventilation** | Opening fully for a short time (default 10 minutes) to exchange air without cooling the building. |

```
            Region North (Street)
     ┌───────────────────────────────┐
     │  Room ──── Window ──── faces ─┼──► Region
     │   │                           │
     │   └─ sources: #1, #2, #3 ...  │     sources: #1, #2 ...
     └───────────────────────────────┘     fallback: neighbours → opposite → weather
 Region West (Yard)            (East: shared wall, no region)
            Region South (Garden)
```

## 4. Functional requirements

### 4.1 Rooms

| ID | Prio | Requirement |
|---|---|---|
| R1 | M | A room is created for exactly one indoor Home Assistant area. The area cannot be used by a second room. |
| R2 | M | The user ranks the **temperature sources** in a sortable list. The highest-ranked valid source wins. |
| R3 | M | Humidity and pressure sources follow the devices of the temperature list in the same order by default (an empty list means "follow"). The user can override them with an own sortable list per metric. If the temperature devices deliver no humidity or pressure (for example sensors without a device), that list is pre-filled at creation from the area's climate-grade sensors of the metric (R6 rules). |
| R4 | M | A source is valid if its value is numeric, it is not `unavailable`/`unknown`, its unit converts to the metric's unit, and it reported within the maximum age (freshness from `last_reported`). |
| R5 | M | `climate` entities contribute their current temperature and, if they report it, their current humidity (`current_humidity`, for example wall thermostats and air conditioners). Never a setpoint. |
| R6 | M | When a room is created, the source list is **pre-filled with climate-grade sources only**: devices with exactly one temperature entity plus humidity first, then devices that only measure and have exactly one temperature entity, `climate` entities last. Not pre-filled: diagnostic entities (device temperature of plugs, routers and similar); temperatures of devices whose main purpose is something else (window and door contacts, motion sensors, lights, air-conditioner outdoor units); devices with several temperature entities (heat pumps, servers); entities without a device; derived values from helper platforms (template, min/max, statistics, filter, comfort calculations); values outside a plausible room range at setup time (for example a fridge). They stay selectable, and the preview names them with the reason. Climate Hub's own entities are never offered, so no source can feed on itself. |
| R7 | M | **Offset learning.** While a higher-ranked source is valid, Climate Hub learns how far each lower-ranked source typically deviates from it (rolling window, about 24 h). When it falls back, it applies the learned offset, so a thermostat that reads 1.2 °C warm does not make the room jump. Offsets are relative to the rank-1 source; a lower source learns against the resolved value whenever a higher-ranked source wins, and reordering the top re-bases the offsets instead of discarding them. At the switch, the offset starts at the last measured deviation and glides to the learned offset within an hour, so the value does not jump. Learned offsets survive restarts and are visible (attribute and diagnostics). Temperature is M, humidity is S. |
| R8 | M | A higher-ranked source takes over again as soon as it is valid. |
| R9 | M | A room can have an outdoor region (its main side). Rooms without an exterior wall have none. The region can be set and changed at any time, in any order relative to creating regions. |
| R10 | M | Derived values per room: absolute humidity, dew point, temperature difference outside − inside, absolute-humidity difference outside − inside, "outside is warmer / colder", position in the comfort range (below / within / above), temperature trend (rising / steady / falling). |
| R11 | M | Climate Hub writes the temperature and humidity entities of each room and outdoor region into the Home Assistant area's *temperature sensor* and *humidity sensor* fields. Default on, confirmed once during setup, can be switched off. When it is switched off, or the room or region is deleted, a field is cleared only while it still holds the entity Climate Hub wrote; the previous value is not restored. A field the user changed after Climate Hub wrote it is left alone. |
| R12 | C | Mould-risk indicator per room (needs a surface-temperature estimate; define when picked up). |
| R13 | S | **Humidity after ventilating:** the relative humidity the room would reach after a full air exchange, computed from the outside vapour pressure at the room temperature. Above 100 % means condensation (for example warm, humid summer air entering a cool cellar). Shown as an attribute of the room's outside absolute-humidity difference. |
| R14 | S | **New sources:** when a climate-grade source (R6) appears later in the area of a room or region, Climate Hub raises a fixable repair issue naming the area and the entity. Fixing it adds the source at the end of the list. Home Assistant's own "ignore" dismisses it for good (one issue per entity). Nothing is added without confirmation (P1). "Later" means after the room or region was last saved: what was in the area then counts as reviewed, including sources the user removed on purpose; an entity created in the area or moved into it afterwards is new. |
| R15 | S | **Heating and cooling devices:** a room knows its `climate` entities in a separate role, pre-filled from the area and editable. Their activity (`hvac_action`, else `hvac_mode`) feeds A12. Climate Hub never controls them. |

Daily minimum and maximum come from Home Assistant's long-term statistics (`state_class`). No extra entities.

### 4.2 Outdoor regions

| ID | Prio | Requirement |
|---|---|---|
| O1 | M | A region is created for exactly one outdoor Home Assistant area and has a compass direction (N, E, S, W). |
| O2 | M | Sources are ranked like room sources (R2–R8), including offset learning. |
| O3 | M | **Automatic fallback** when a region has no valid source: adjacent directions (90°), then the opposite direction (180°), then the hub's weather entity, then unavailable. If several regions qualify at the same stage, their mean is used. |
| O4 | M | There is **no fallback configuration**. No region depends on another region being configured first. |
| O5 | M | The weather entity delivers temperature, humidity and pressure from its attributes, with its own maximum age (2 h, not configurable). While a region's own sensors work, Climate Hub learns how far the weather's current values deviate from them. When the weather stands in (O3), its values are corrected by that region's offset; a direction without a region and the house-level value use the mean offset. A street that runs warmer than the weather service stays warmer, and pressure does not jump between sea-level and station pressure. |
| O6 | M | Derived values (absolute humidity, dew point) use temperature and humidity from the **same region and stage**. They walk the fallback chain on their own and take the first stage where both are available from the same regions, so they can come from another stage than the displayed temperature. If no stage has both, the derived values are unavailable rather than mixed. |
| O7 | M | House-level outdoor value: mean of all valid regions, with minimum, maximum and the per-region values as attributes. It is for display and automations only. Recommendations always use the room's own region (A2), and fallbacks use neighbouring regions (O3). |
| O8 | C | Learned offsets between regions (time-of-day dependent because of the sun). |
| O9 | C | **Ventilation preference per region** (preferred / normal / avoid, default normal). Captures what sensors cannot measure: still air, traffic noise and exhaust, a breeze from nearby water. Used as a tie-breaker when a room has windows on several sides and for cross-ventilation hints (A9). |
| O10 | C | **Sun-exposure plausibility:** flag a region whose sensor deviates strongly from the other regions while the sun shines on that side (sensor in direct sun reads too high). |

Regions measure the air right outside each side on purpose. A street side heated by asphalt or a garden side cooled by
plants is real air that enters the window, so it must not be "corrected" towards a regional average.

### 4.3 Windows

| ID | Prio | Requirement |
|---|---|---|
| W0 | M | Windows are an optional add-on. Rooms, regions and the recommendation work without any window. Without windows the recommendation only says `open` or `close` (the `keep_*` states need a window state), and the warnings (A4) need at least one window. The first setup offers adding windows as an optional last step; they are never guessed. |
| W1 | M | A window belongs to a room and faces a region. The region defaults to the room's region and can be changed. |
| W2 | M | Contacts are `binary_sensor` entities (device class window, door, opening, garage door) or text sensors with a configurable state mapping. |
| W3 | M | Opening levels: closed < ajar < tilted < open. A window counts as **ventilating** from a minimum level (default: tilted; ajar does not count). |
| W4 | M | Contact roles cover real hardware setups: **leaf contacts** (double-leaf windows: open if any leaf is open, report which leaves), **tilt discriminator** (one contact tells tilted from turned open), **handle contact** (handle turned while sash closed means ajar). |
| W5 | S | **Pass-through window:** ventilating a room requires several openings in series, for example an interior door plus the window of an adjacent conservatory. Open only if all are open. |
| W6 | M | One contact may be used by more than one window (needed for W5). |
| W7 | M | Outputs: window state (closed / ajar / tilted / open, with open leaves as attribute) and "open since" (timestamp). "Open since" means ventilating since (W3): an ajar window has none, and changes between ventilating levels keep it. |
| W8 | M | Unknown or unavailable contacts are never interpreted as closed. An unknown opening contact (leaf, pass-through opening) makes the state unknown unless the known contacts already decide it (a known open leaf, a known closed opening of a pass-through). Unknown refining contacts (tilt discriminator, handle) are ignored. A tilt discriminator that reports open proves the window open. If no contact is usable, the window state is unavailable. |
| W9 | M | A room can have any number of windows, also facing different sides. Two leaves of one frame are **one** window (W4), two frames are two windows. The room aggregates its windows: the most open level, the earliest "open since", and "ventilating" if any window ventilates. |
| W10 | S | Contact changes are debounced (a few seconds), so a bouncing contact neither resets "open since" nor triggers automations. "Open since" is persisted, so a restart does not reset it; without a stored value it comes from the contact's last change, not from the restart time. |
| W11 | M | Deleting a room keeps its windows. They keep reporting their state; room-dependent outputs report `none` with reason `no_room`. A fixable repair issue per area offers to recreate the room (with suggested sources) or to delete those windows. Home Assistant's delete dialog cannot warn beforehand, so nothing is deleted implicitly. |
| W12 | M | A double leaf with a shared tilt discriminator follows the table below (scenario 5). The discriminator sits where only a turned leaf can open it, for example at the bottom between the leaves. |

Double leaf with a shared tilt discriminator (W12). 1 = contact reports open.

| Left leaf | Right leaf | Discriminator | State | Open leaves |
|---|---|---|---|---|
| 0 | 0 | 0 | closed | none |
| 1 | 0 | 0 | tilted | left |
| 0 | 1 | 0 | tilted | right |
| 1 | 1 | 0 | tilted | both |
| 1 | 0 | 1 | open | left |
| 0 | 1 | 1 | open | right |
| 1 | 1 | 1 | open | both (one may be tilted; not distinguishable and irrelevant, the most open level wins) |
| 0 | 0 | 1 | open | unknown (implausible, a leaf contact is probably faulty; never reported as closed, W8) |

### 4.4 Ventilation recommendation

| ID | Prio | Requirement |
|---|---|---|
| A1 | M | **Daily strategy** (hub): the forecast maximum of the next 24 hours above comfort maximum + threshold means *prevent heat-up*. The forecast minimum of the next 24 hours below comfort minimum − threshold means *prevent cool-down*. If both apply, *prevent heat-up* wins. Otherwise *neutral*. Forecast from the hub's weather entity (hourly; with a daily forecast only, today's entry). |
| A2 | M | **Recommendation per room:** `open`, `keep_open`, `close`, `keep_closed` or `none`, plus a translated reason. Rules (detailed in `docs/logic.md`): the window is wanted open only for a reason, otherwise closed with the reason why. On any day, a room above the comfort range opens while outside is cooler, down to the middle of the range, and a room below it opens while outside is warmer, up to the middle. On *prevent heat-up* days, a room also opens while outside is cooler, down to the comfort minimum (pre-cooling), and closes while outside is warmer. On *prevent cool-down* days, a room within the range keeps closed; humidity bursts (A3) are the exception. |
| A3 | M | **Humidity rule:** if the room's relative humidity exceeds a threshold (default 60 %) and outside air is absolutely drier by a margin, recommend ventilation. If opening does thermal harm (colder outside on a *prevent cool-down* day or in a room below the range, warmer outside on a *prevent heat-up* day or in a room above the range), it is a burst for the burst time, followed by a pause of one hour before the next burst. Otherwise it continues until the target of A6. |
| A4 | M | **Warnings per room** (binary sensors): *cooling down* (window open beyond the burst time on a cool-down day while outside is colder) and *heating up* (window open beyond the burst time on a heat-up day while outside is warmer or the room temperature is rising). Neither fires while the recommendation wants the window open. House-level "any room" variants exist for automations. |
| A5 | M | Missing data gives `none` with reason `no_data`, never a silent `keep_closed`. |
| A6 | M | **Hysteresis, ventilate to a target.** Once ventilation starts for cooling, the recommendation stays `keep_open` until the room reaches the middle of the comfort range or outside is no longer cooler. Ventilation for humidity starts above the threshold (default 60 %) and continues until 5 points below it. Comparisons use small margins per unit (°C, g/m³, % RH; for example "outside is cooler" needs at least 0.5 °C), so recommendations do not flap when values are close. |
| A7 | C | **Air-quality rule (general):** an optional air-quality source per room (for example CO₂) with a high threshold that recommends ventilation. Burst ventilation then ends after the burst time **or** when air quality is back below a low threshold. |
| A8 | C | Forecast extras: overheating risk over the next days and the next time outside drops below the comfort maximum ("best time to ventilate"). |
| A9 | C | **Cross-ventilation hint:** when rooms on opposite sides both recommend opening, suggest opening them together, preferring regions marked *preferred* (O9). |
| A10 | S | If a room's windows face different sides, the recommendation names the window whose side helps most (coolest air when cooling, driest air when dehumidifying). A region preference (O9) breaks ties. |
| A11 | C | **Time to close:** a timestamp for when the current ventilation will likely have reached its goal (room temperature or humidity trend plus outside values). |
| A12 | S | **Open while heating or cooling:** binary sensor per room that turns on when a window ventilates longer than the burst time while one of the room's heating or cooling devices (R15) is active. A house-level "any room" variant exists for automations. Needs windows and R15. |
| A13 | M | **Humidity guard:** no ventilation for temperature (A2) while the humidity after ventilating (R13) would reach the humidity threshold, released 5 points below it. Protects cellars and cool rooms from humid summer air (scenario 12). |
| A14 | S | **Forecast bias:** once a day, Climate Hub compares the forecast maximum and minimum with what the house's own outdoor sensors measured and learns the typical deviation (about a week of memory, applied after three days). The daily strategy (A1) uses the corrected forecast. No setting; raw and corrected values are attributes of the strategy entity. |

### 4.5 Covers

Climate Hub **recommends** what to do with a window's cover: keep sun and heat out by day, keep warmth in at night,
let the sun in when its warmth is welcome. It never moves covers. Automations act on the recommendation, and existing
cover automations keep working unchanged; they can adopt the recommendation step by step.

| ID | Prio | Requirement |
|---|---|---|
| SH1 | S | **Cover recommendation per window:** `close`, `keep_closed`, `open`, `keep_open` or `none`, plus a translated reason. By day, close when the sun shines on the window (sun azimuth within about ±60° of the window's facing, elevation above a minimum, enough sun after cloud cover) **and** the day is *prevent heat-up* or the room is near or above the comfort maximum (sun protection), and on *prevent heat-up* days while outside is warmer than the room, even without sun (heat barrier). At night (sun below the horizon), close on *prevent cool-down* days or in a room below the comfort range while outside is colder (cold barrier); otherwise no recommendation. Never close by day when the room is below the comfort minimum or it is cold outside, because the solar gain is welcome then. Never close while the window or door is fully open. Hysteresis and a minimum hold time prevent flapping. Automations filter by reason (for example sun protection only), so there is no setting. A house-level "any cover to close" binary sensor exists for automations. |
| SH2 | S | **Optional cover per window** (`cover` entity). With a cover, the recommendation knows the current position and can say `keep_*`. A cover is never treated as a window contact. The cover recommendation exists for every window and is enabled by default only when a cover is assigned. A cover assigned later enables the entity if Climate Hub had disabled it; one the user disabled stays disabled. |
| SH3 | C | Optional sun-intensity source on the hub (illuminance or irradiance sensor). Default: cloud cover from the weather entity. |
| SH4 | C | Exact facing of a window in degrees (expert field), for windows that face differently than their room's side. Default: derived from the facing direction (N = 0°, E = 90°, S = 180°, W = 270°). |

### 4.6 Hub and house level

| ID | Prio | Requirement |
|---|---|---|
| H1 | M | Exactly one Climate Hub entry per Home Assistant instance. |
| H2 | M | Comfort range as **number entities** on the hub device (minimum, maximum, threshold; defaults 20 °C, 24 °C, 2 °C), global, changeable by automations. A value that would make the minimum reach or pass the maximum is rejected with a translated error, and the old value stays. |
| H3 | M | One weather entity for the forecast (A1) and as the last outdoor fallback (O3). Editable at any time. |
| H4 | M | House-level sensors: indoor average (with min/max attributes), outdoor (O7), daily strategy (A1), "any room cooling down / heating up" (A4). |
| H5 | S | **Sensor problems as repairs:** if a source stays invalid for a long time (default 6 h), a Home Assistant repair issue names the room, the source and the active fallback. It resolves itself when the source is back. |
| H6 | M | Global defaults for expert values (maximum age, burst duration, humidity threshold, repair delay) live in the hub options. Margins and hysteresis are constants (`docs/logic.md` §13). |

### 4.7 Setup and editing

| ID | Prio | Requirement |
|---|---|---|
| U1 | M | **Guided first setup in a few screens:** Climate Hub scans areas, sensors and weather entities, then proposes rooms and outdoor regions. Floors help the proposal (areas on a floor that sounds like outside are proposed as outdoor areas), but are never required. The user confirms or deselects. Nothing is created without confirmation. Windows can be added as an optional last step or later (W0). |
| U2 | M | Rooms, regions and windows each have their own add, edit and delete. Changes take effect without a restart. |
| U3 | M | Every field from creation is editable later, including fields that were left empty. |
| U4 | M | No creation-order dependencies (P3). Adding a window in an area that has no room yet creates the room with suggestions (after confirmation) instead of failing. |
| U5 | M | Priorities are set by sorting a list. There are no rank dropdowns. |
| U6 | M | Pickers are filtered by context: entities of the object's area plus entities without any area. Already selected entities always stay visible. If the filter finds nothing, it is lifted. Window forms offer "show all contacts", which re-opens the form unfiltered; the outer opening of a pass-through always lists all contacts, because it usually lies in another area (W5). |
| U7 | M | **Preview before saving** with live values: "Temperature 21.4 °C from source #1, humidity 48 %, outside (North) 12.1 °C, stage primary". |
| U8 | M | All texts come from translations (English and German). Every field has a short description. Domain terms come with an example sentence. |
| U9 | M | Expert values sit in collapsed sections with good defaults. A typical room needs zero expert values. |
| U10 | M | Mockups (screens, fields, texts, errors) are approved before UI code is written. |
| U11 | M | Decision point after the mockups and the first DEV test: if the native UI cannot meet U1–U9, move management into a custom panel. **Decided 2026-10-13: native UI** (every mechanism the approved mockups need works natively, `docs/ui_mockups.md` §7; ADR-001). |

### 4.8 Entities and naming

| ID | Prio | Requirement |
|---|---|---|
| E1 | M | Entity names come from translations (`has_entity_name`). Measurements carry device class and state class, so they get long-term statistics. |
| E2 | M | One device per room, region and window, placed in the matching area. The hub device is a service device. |
| E3 | M | Entity IDs are predictable from the area, so one dashboard template serves all rooms (P7). Device names carry no product prefix and no area, because Home Assistant puts the area in front of entity IDs (ADR-007): rooms and regions are named "Climate" ("Klima"), windows "Window" ("Fenster", numbered from the second window in a room; pass-through "Durchgang") or the user's name, the hub device "Home climate" ("Hausklima"). Devices sit in their area. Example: `sensor.kuche_klima_temperatur`. |
| E4 | M | Enumerations (recommendation, reason, strategy, window state, comfort position, trend) are enum sensors with translated states and stable raw states. |
| E5 | M | Unique IDs are based on the subentry, never on display names. Renaming never breaks history. |
| E6 | M | Each measurement exposes a small, stable attribute set (source, stage, reason, learned offset). Volatile details are excluded from the recorder. The full decision chain is in diagnostics. |

## 5. Non-functional requirements

| ID | Requirement |
|---|---|
| N1 | Event-driven: recompute on source state changes (debounced), plus a periodic tick for freshness and timers. No polling of sources. |
| N2 | Failures are isolated per room, region and window. One broken object never affects the others. |
| N3 | Calculation logic is pure Python without Home Assistant imports and has table tests. Flows are tested end to end through the flow manager. |
| N4 | Learned and timed state (offsets, open-since, trend, burst timers) survives restarts. |
| N5 | No registry scans per update. Sources are resolved when the configuration or the registries change. |
| N6 | Minimum Home Assistant version 2026.10.0 (ADR-008). |
| N7 | Nothing is built that the UI cannot reach. No placeholders, no dormant code paths. |

## 6. Acceptance scenarios

These come from a real installation and must work without workarounds:

1. **Kitchen with noise:** the kitchen area also holds a fridge sensor and a 3D printer. Setup pre-fills only the room climate sensor and the thermostat (last).
2. **Thermostat offset:** the room sensor goes offline for two hours. The room value continues from the thermostat, corrected by its learned offset, without a visible jump.
3. **Three sides and a shared wall:** regions North (street), West (yard) and South (garden), no East. North's sensor fails and the value comes from West (adjacent), then South (opposite), then weather.
4. **First region alone:** the user creates the North region before any other. It works, and its fallback skips straight to weather.
5. **Double-leaf window:** two leaf contacts plus one tilt discriminator report "tilted, left leaf" or "open, both leaves".
6. **Handle contact:** sash contact closed and handle turned gives "ajar". Ajar does not count as ventilating.
7. **Pass-through:** a room ventilates only when its door to the conservatory **and** the conservatory window are both open.
8. **Contacts without area:** window contacts that have no area are still offered in the window form.
9. **Humid bathroom in winter:** on a *prevent cool-down* day, humidity of 68 % and drier air outside give the recommendation `open` (burst ventilation), then `close` after the burst time.
10. **Any order:** creating window → room → region gives the same result as region → room → window.
11. **No ping-pong:** on a neutral day with a comfort range of 20–24 °C, a room at 24.6 °C with 19 °C outside gets `open`. It stays `keep_open` at 23.9 °C and changes to `close` only at 22 °C or when outside stops being cooler.
12. **Summer cellar:** outside 24 °C at 70 %, cellar at 20 °C. Humidity after ventilating shows about 89 %, and the recommendation does not suggest ventilating to dry the cellar.

## 7. Out of scope (for now)

- Heating control. Heating may later consume Climate Hub's room values.
- Energy exchange and solar gain per window (physical window model). May be folded into windows much later. The
  cover recommendation (4.5) works with rules, not with an energy model.
- Exotic comfort indices (heat index, humidex and similar).
- Moving covers. Climate Hub recommends what to do with them (4.5); automations act on it.
- A custom management panel, unless U11 triggers it.

## 8. Open questions

| # | Question |
|---|---|
| ~~Q5~~ | Confirmed 2026-10-13: maximum age 40 min, burst time 10 min, humidity threshold 60 %, repair delay 6 h. |
| ~~Q6~~ | Decided 2026-10-14: minimum Home Assistant 2026.10.0 (ADR-008). The UI alone would need 2025.10 (`reorder` 2025.8, menu option descriptions 2025.10); entity IDs with the area and `probatio` set the rest. Drag-sorting inside a subentry flow confirmed on DEV. |
