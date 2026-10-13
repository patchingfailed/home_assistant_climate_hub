# Logic specification

Status: **draft**, 2026-10-13. First review done: D1–D12 and D14 approved, D13 replaced by D16; D15 and D16
pending. Covers the pure modules in `custom_components/climate_hub/logic/`
(rule 6: no Home Assistant imports, `now` is a parameter, table tests). Requirement IDs refer to
`docs/requirements.md`, ADRs to `docs/architecture.md`, screens to `docs/ui_mockups.md`.

Each module section has the requirements it covers, its interface (a sketch: names may be refined during the build,
semantics may not), its rules, and table cases. The table cases are the acceptance tests: every row becomes a
parametrised pytest case in `tests/logic/`.

## 0. Review first: decisions this spec makes

The requirements leave these points open or state them in a way the logic cannot implement literally. Each one has a
proposal. Approved proposals that change requirement wording are folded into `docs/requirements.md`.

| # | Topic | Proposal | Requirement impact |
|---|---|---|---|
| D1 | Offset learning at the switch | Learned offset is a time-weighted moving average (time constant 8 h, about 24 h of memory). When a fallback takes over, its offset starts at the last measured deviation and glides to the learned offset within 60 min, so the value does not jump (scenario 2). | R7: adds the glide |
| D2 | Offset reference | Offsets are relative to the rank-1 source's scale. A lower source learns against the resolved value whenever a higher-ranked source wins. Moving another source to rank 1 re-bases all offsets instead of discarding them. | R7: clarifies |
| D3 | Outdoor derived values | Absolute humidity and dew point walk their own chain: the first stage where temperature **and** humidity come from the same regions. They can therefore come from another stage than the displayed temperature, but they are never mixed. | O6: interpretation |
| D4 | Daily strategy horizon | Use the **next 24 hours** of the hourly forecast, so the strategy at 22:00 already sees tomorrow's heat (night pre-cooling). Daily forecast only as a fallback (today's entry). If a day crosses both thresholds, *prevent heat-up* wins. | A1: "today" becomes "next 24 h" |
| D5 | Recommendation is binary | A room wants the window **open only for a reason** (cool, warm, dry). Otherwise it wants it closed and says why (`in_range`, `outside_colder` …). An overheated room opens to cool even on a *prevent cool-down* day, down to the middle of the comfort range. | A2: neutral and cool-down rules refined |
| D6 | Pre-cooling bound | On *prevent heat-up* days, ventilate while outside is cooler, down to the comfort **minimum** (bank coolness), never below. | A2: adds the lower bound |
| D7 | Humidity ventilation | Continuous until 5 points below the threshold when opening does no thermal harm. A timed burst when it does harm (cool-down day and colder outside, heat-up day and warmer outside, …). After a burst, a **1 h pause** before the next one. | A3/A6: adds the pause |
| D8 | Humidity guard (new) | No thermal ventilation when the humidity after ventilating (R13) would reach the humidity threshold (60 %). Protects cellars and cool rooms from humid summer air. | New rule under A6 |
| D9 | Unknown contacts | Opening contacts (leaves, pass-through openings) are strict: the state is never `closed` by assumption. Refining contacts (tilt discriminator, handle) are ignored when unknown. A discriminator reporting open proves open. | W8: interpretation |
| D10 | "Open since" | Means **ventilating** since (from the minimum level, default tilted). An ajar window has no "open since". Persisted across restarts. | W7/W10: clarifies |
| D11 | Humidity after ventilating (R13) | Attribute `humidity_after_ventilating` on "Feuchtedifferenz außen" (approved). | §6 / R13 |
| D12 | Warnings | Both warnings (A4) allow the burst duration as grace and never fire while the recommendation says `keep_open`. | A4: clarifies |
| ~~D13~~ | ~~Shading at night~~ | Replaced by D16 (review 2026-10-13: a closed cover is also a cold and heat barrier). | – |
| D14 | Constants | Margins and hysteresis are constants (§13), not hub options. Approved S9 has no hysteresis field; H6 mentions one. Weather maximum age is a constant (2 h). Comfort defaults 20 / 24 / 2 °C. | H6 wording, O5 |
| D15 | Local weather bias (idea from the review) | Two learned corrections, no settings. **Forecast bias:** once a day, compare the forecast maximum and minimum with what the house's own outdoor sensors measured; the strategy uses the forecast plus the learned bias (A1). **Weather offset per side:** while a region's sensors work, learn how far the weather entity's current values deviate from them; when the weather stands in (O3), it is corrected by that offset, so a street that runs 2 °C warmer stays 2 °C warmer and pressure does not jump by the sea-level difference. | New A14; O5 |
| D16 | Cover as a thermal barrier | The per-window shading output becomes a **cover recommendation** with the states of the window recommendation (`close`, `keep_closed`, `open`, `keep_open`, `none`) and a reason: sun protection (`sun_heat`), heat barrier by day on hot days even without sun (`heat_barrier`), cold barrier at night on cool-down days (`insulate`), solar gain welcome (`solar_gain`). Never `close` while the window is fully open (lock-out at doors). Automations filter by reason, so no setting is needed. | SH1, SH2; mockups §6 (entity name and states) |

## 1. Conventions

- **Units.** The logic works in °C, % RH, hPa, g/m³, K/h. The adapter converts source values with Home Assistant's
  unit converters before they reach the logic. A unit that does not convert makes the reading invalid (status `unit`,
  R4). Outputs are in the same units; Home Assistant converts them for display.
- **No value** is `None`. The logic never raises for missing data. It returns `None` plus a reason.
- **No rounding** in the logic. Comparisons use unrounded values; entities round for display.
- **Time.** `now` is a timezone-aware `datetime` in local time (the adapter passes `dt_util.now()`). Durations are
  `timedelta`. Ages are `now - reported_at`; a reading exactly at the maximum age is still fresh.
- **Hysteresis** is written as *enter* and *exit* thresholds. A state is entered at the enter threshold and kept until
  the exit threshold is crossed. Every hysteresis function takes the previous state; `None` means "no previous state"
  (start-up) and uses the enter thresholds only.
- **State.** Every stateful function takes its previous state and returns a new immutable state. The adapter persists
  the states marked *persisted* (N4) in a `Store` and passes them back. Nothing in the logic keeps state between calls.
- **Three-valued logic.** Booleans that depend on unknown inputs are `True`, `False` or `None`. "Any" aggregations are
  `True` if any input is `True`, `False` if all inputs are known and `False`, `None` otherwise.
- **Constants** live in one module (`logic/const.py`) and are listed in §13.

## 2. Data flow

One evaluation per coordinator update (state change, debounced, or the 60 s tick, N1). Each object is evaluated on its
own; an error in one object is caught by the adapter and leaves the others intact (N2).

```
snapshot (adapter: readings converted, contacts, climate activity, weather, forecast, sun, covers, comfort numbers)
  1. sources       per room and region metric      → Resolution          (offset state persisted)
  2. outdoor       per direction                   → OutdoorValues        (+ house outdoor; weather offsets persisted)
  3. comfort       per room: derived values, comfort position, outside relation, trend   (trend persisted)
  4. strategy      hub                             → Strategy             (previous strategy; forecast bias persisted)
  5. window        per window, then per room       → WindowState          (open-since persisted)
  6. recommendation per room: recommendation, warnings, open while conditioning          (goal state persisted)
  7. cover         per window                      → CoverResult          (hold state persisted)
  8. house         indoor average, any-room flags, any cover to close, source outages (H5) (outage state persisted)
```

`prefill` (§11) is not part of the evaluation. Flows call it when sources are suggested, and the R14 listener calls
it when a new entity appears.

## 3. Module `psychro` (R10, R13, O6)

Magnus formula over water (Alduchov and Eskridge 1996), used for all temperatures, including below 0 °C (weather
services report relative humidity over water).

```
SVP(T)  [hPa]  = 6.1094 · exp(17.625 · T / (243.04 + T))
VP      [hPa]  = SVP(T) · RH / 100
AH      [g/m³] = 216.68 · VP / (273.15 + T)
DP      [°C]   = 243.04 · γ / (17.625 − γ),  γ = ln(VP / 6.1094)
RH_after [%]   = 100 · VP_out / SVP(T_room) = 100 · SVP(DP_out) / SVP(T_room)          (R13)
```

```python
def absolute_humidity(t: float, rh: float) -> float | None
def dew_point(t: float, rh: float) -> float | None
def humidity_after_ventilating(t_room: float, dew_point_out: float) -> float
```

Rules:
- `rh <= 0` gives `None` (dew point undefined). `rh > 100` is clamped to 100 (sensor noise).
- `humidity_after_ventilating` is not clamped: above 100 % means condensation (R13).

| T °C | RH % | AH g/m³ | DP °C |
|---|---|---|---|
| 20 | 50 | 8.62 | 9.26 |
| 20 | 60 | 10.35 | 12.00 |
| 22 | 65 | 12.59 | 15.12 |
| 0 | 80 | 3.88 | −3.04 |
| −10 | 90 | 2.13 | −11.33 |
| 30 | 40 | 12.11 | 14.93 |
| 25 | 100 | 22.98 | 25.00 |
| 25 | 104 | 22.98 | 25.00 (clamped) |
| 20 | 0 | None | None |

| Outside | Room | RH after ventilating | Note |
|---|---|---|---|
| 24 °C, 70 % | 20 °C | 89.3 % | Scenario 12 ("about 89 %") |
| 5 °C, 85 % | 21 °C | 29.8 % | Winter air dries |
| 25 °C, 80 % | 18 °C | 122.8 % | Condensation, not clamped |

Tolerance in tests: ±0.01 for AH and DP, ±0.1 for RH after ventilating.

## 4. Module `sources` (R2, R4, R5, R7, R8, O2, O5, E6)

Resolves one metric of one room or region from its ranked source list.

```python
class Status(StrEnum):  # set by the adapter, except STALE
    OK, UNAVAILABLE, UNKNOWN, NOT_NUMERIC, UNIT, MISSING, STALE

@dataclass(frozen=True)
class Reading:
    entity_id: str
    value: float | None          # converted to the metric's unit; None unless status is OK
    status: Status
    reported_at: datetime | None # last_reported

@dataclass(frozen=True)
class Offset:                    # persisted, per (object, metric, entity)
    learned: float               # moving average of (source − reference)
    paired: timedelta            # accumulated paired time, capped at the time constant
    last_sample_at: datetime
    last_deviation: float        # most recent (source − reference)

@dataclass(frozen=True)
class SourceState:               # persisted, per (object, metric)
    offsets: dict[str, Offset]
    rank1: str | None            # entity at rank 1 when offsets were last updated
    winner: str | None
    switched_at: datetime | None # when the current winner took over from a higher-ranked one
    anchor: float | None         # winner's deviation at switched_at (D1 glide)

@dataclass(frozen=True)
class Resolution:
    value: float | None
    source: str | None
    rank: int | None             # 1-based
    stage: Stage                 # PRIMARY, FALLBACK or NONE here
    offset: float | None         # applied offset, only for FALLBACK
    reason: Status | None        # status of the rank-1 source when stage is not PRIMARY
    candidates: tuple[Candidate, ...]  # every source with status, raw value, learned offset (diagnostics)

def resolve(readings: Sequence[Reading], max_age: timedelta, state: SourceState | None,
            now: datetime, bounds: tuple[float, float] | None) -> tuple[Resolution, SourceState]
```

Rules:
1. A reading is **valid** if its status is `OK` and `now − reported_at ≤ max_age`; otherwise `STALE` is set (R4).
   The weather entity is a reading with its own maximum age (O5, constant 2 h, D14).
2. The first valid reading in rank order wins (R2). A higher-ranked source wins again as soon as it is valid (R8).
   There is no switch hysteresis (ADR-004).
3. Rank 1 has no offset. A lower-ranked winner's value is `raw − applied_offset`, clamped to `bounds` (humidity
   0–100 %).
4. **Learning (D2).** On every evaluation, each valid source ranked **below** the winner takes a sample
   `d = raw − resolved_value`. The moving average uses `α = 1 − exp(−Δt / 8 h)` with `Δt` the time since its last
   sample, capped at 30 min (a gap must not let one sample dominate). The first sample initialises `learned = d`.
   The winner and sources ranked above it do not learn.
5. A source counts as **learned** once `paired ≥ 1 h`; before that the preview says "Abweichung wird gelernt" and the
   offset is still applied.
6. **Glide (D1).** When a lower-ranked source takes over from a higher-ranked one, `anchor = last_deviation` if that
   sample is not older than `max_age`, else `anchor = learned`. The applied offset is
   `learned + (anchor − learned) · max(0, 1 − (now − switched_at) / 60 min)`. A takeover by a higher-ranked source
   (R8) is immediate and has no glide.
7. **Re-base (D2).** If the rank-1 entity differs from `state.rank1` and the new rank-1 has a learned offset `o`, every
   offset is shifted by `−o` (the old rank 1 gets `−o`). If the new rank-1 has no offset, all offsets are dropped.
   Offsets of entities no longer in the list are dropped.
8. Every metric (temperature, humidity, pressure) uses the same mechanism (R7: temperature M, humidity S; pressure
   comes for free and absorbs sea-level vs. station pressure).
9. `climate` entities deliver `current_temperature` and `current_humidity` (R5). The adapter builds their readings;
   a missing attribute is status `UNKNOWN`. Setpoints are never read.

Resolution cases (temperature, `max_age` 40 min, now 12:00, offsets learned: #2 +0.3, #3 +1.2, no glide running):

| # | Source 1 | Source 2 | Source 3 | Value | Source | Stage | Reason |
|---|---|---|---|---|---|---|---|
| 1 | 21.4, 11:55 | 21.7, 11:50 | 22.6, 11:58 | 21.4 | #1 | primary | – |
| 2 | 21.4, 11:15 (stale) | 21.7, 11:50 | 22.6 | 21.4 | #2 | fallback (offset 0.3) | stale |
| 3 | 21.4, 11:20:00 (exactly 40 min) | 21.7 | 22.6 | 21.4 | #1 | primary | – |
| 4 | unavailable | unavailable | 22.6 | 21.4 | #3 | fallback (offset 1.2) | unavailable |
| 5 | not numeric | 21.7 | 22.6 | 21.4 | #2 | fallback | not_numeric |
| 6 | unit `lx` | 21.7 | 22.6 | 21.4 | #2 | fallback | unit |
| 7 | all unavailable | | | None | – | none | unavailable |
| 8 | empty list | | | None | – | none | – |

Humidity clamp: rank-2 raw 99.0 % with learned offset −2.0 → 101.0 → **100.0**.

Learning cases (`τ` 8 h, cap 30 min):

| Learned before | Sample | Δt since last sample | Learned after |
|---|---|---|---|
| – (first sample) | 1.0 | – | 1.0 |
| 1.0 | 1.2 | 1 min | 1.000416 |
| 1.0 | 2.0 | 10 min | 1.0206 |
| 1.0 | 2.0 | 2 h (capped to 30 min) | 1.0606 |
| 1.0 | constant 2.0 every minute for 1 h / 8 h / 24 h | | 1.118 / 1.632 / 1.950 |

Learning gate: while #1 wins, #2 and #3 learn. While #2 wins, only #3 learns (against the resolved value). An invalid
source never learns.

Glide cases (#1 goes stale and #2 takes over at 12:00; #2 has learned 1.0, its last deviation 1.6 was measured at 11:59):

| Now | Applied offset |
|---|---|
| 12:00 | 1.6 |
| 12:30 | 1.3 |
| 13:00 | 1.0 |
| 13:30 | 1.0 |
| 12:00, but last deviation from 11:00 (older than max age) | 1.0 |

Re-base cases (offsets #2 +0.3, #3 +1.2 relative to #1):

| Change | Offsets after |
|---|---|
| #3 moved to rank 1 | old #1: −1.2, old #2: −0.9, #3: none (rank 1) |
| #2 and #3 swapped | unchanged |
| new entity X put at rank 1 | all dropped |
| #3 removed from the list | #3 dropped, #2 unchanged |

## 5. Module `outdoor` (O1–O7, ADR-003, scenarios 3 and 4)

```python
class Direction(StrEnum): N, E, S, W

@dataclass(frozen=True)
class RegionOwn:                     # one configured region, own sources already resolved (§4)
    direction: Direction
    temperature: Resolution
    humidity: Resolution
    pressure: Resolution

@dataclass(frozen=True)
class OutdoorValue:
    value: float | None
    stage: Stage                     # PRIMARY, FALLBACK, NEIGHBOUR, OPPOSITE, WEATHER, NONE
    regions: tuple[Direction, ...]   # regions the value came from (empty for WEATHER/NONE)
    reason: str | None

@dataclass(frozen=True)
class OutdoorValues:                 # what a direction (and every room facing it) sees
    temperature: OutdoorValue
    humidity: OutdoorValue
    pressure: OutdoorValue
    absolute_humidity: OutdoorValue  # pair chain (D3)
    dew_point: OutdoorValue          # pair chain (D3)

@dataclass(frozen=True)
class WeatherOffsets:                # persisted: per (direction, metric) an Offset (§4) of weather − own value
    offsets: dict[tuple[Direction, Metric], Offset]

def fallback_chain(direction: Direction, configured: set[Direction]) -> list[tuple[Stage, tuple[Direction, ...]]]
def learn_weather_offsets(regions, weather: WeatherReadings | None, state: WeatherOffsets | None,
                          now: datetime) -> WeatherOffsets
def resolve_direction(direction, regions: Mapping[Direction, RegionOwn], weather: WeatherReadings | None,
                      offsets: WeatherOffsets) -> OutdoorValues
def house_outdoor(regions, weather, offsets) -> HouseOutdoor   # O7
```

Rules:
1. **Chain** for a direction: own region (if configured), the two adjacent directions (90°), the opposite direction
   (180°), the weather entity, none (O3). Directions without a region are skipped; the direction itself always exists
   (ADR-003). There is no configuration (O4).
2. A region **qualifies** at a stage only with a valid value from its **own** sources (primary or fallback). Fallback
   values of other regions never feed a chain (no recursion, any creation order gives the same result, P3).
3. Several qualifying regions at the same stage: their **mean** (O3).
4. Each metric walks the chain on its own. Stage `primary` or `fallback` means the direction's own region.
5. **Pair chain (D3, O6).** Absolute humidity and dew point walk the same chain, but a region qualifies only if both
   its temperature and humidity are valid from its own sources. Each region computes AH and DP from its own pair; at a
   multi-region stage the outputs are the means of the regions' AH and DP. At the weather stage they come from the
   weather's corrected temperature and humidity (rule 9). If no stage has a pair, both are `None` with reason
   `no_pair`.
6. Own pair stage: `fallback` if temperature or humidity came from a fallback source, else `primary`.
7. A room without a main side gets all outdoor values `None` with reason `no_side`.
8. **House outdoor (O7):** mean temperature of all regions with own valid values, with min, max and per-region values.
   Without any such region: the corrected weather value (stage `weather`, rule 9). Display and automations only;
   recommendations always use the room's own direction.
9. **Weather offsets (D15).** While a region's own value of a metric and the weather's value are both valid, the
   region learns `d = weather − own` with the offset learner of §4 (rules 4 and 5, no glide, no re-base). At the
   weather stage the value is `weather − offset`: the direction's own offset if it has a region, else the mean of all
   regions' learned offsets of that metric, else the raw weather value. Humidity is clamped to 0–100 % after the
   correction. Offsets of removed regions are dropped. Attributes show the applied offset (E6).

Inter-region offsets (O8) stay out of scope: neighbour and opposite stages use the regions' values unchanged.

Chain cases:

| Configured | Direction | Chain |
|---|---|---|
| N, W, S | N | own N → neighbour W → opposite S → weather |
| N, W, S | E | neighbours N + S → opposite W → weather |
| N, W, S | S | own S → neighbour W → opposite N → weather |
| N, W, S | W | own W → neighbours N + S → weather (E not configured) |
| N | N | own N → weather (scenario 4) |
| none | S | weather |

Value cases (N 13.0 °C / 71 %, S 12.5 °C / 76 %, W 14.5 °C / 65 %, weather 11.0 °C / 80 %; configured N, W, S;
no weather offsets learned yet):

| Direction | Failing own sources | Temperature | Stage | AH g/m³ | AH stage |
|---|---|---|---|---|---|
| N | none | 13.0 | primary | 8.04 | primary |
| N | N temperature and humidity | 14.5 (W) | neighbour | 8.07 (W) | neighbour |
| N | N and W | 12.5 (S) | opposite | 8.34 (S) | opposite |
| N | N, W, S | 11.0 | weather | 7.99 | weather |
| N | N, W, S; weather stale | None | none | None | none |
| N | only N humidity | 13.0 (N) | primary | 8.07 (W) | neighbour (D3) |
| E | none | 12.75 (mean N, S) | neighbour | 8.19 (mean) | neighbour |
| E | N temperature | 12.5 (S only) | neighbour | 8.34 (S only, N has no pair) | neighbour |

Dew point at stage E/neighbour: 8.12 (mean of 7.86 and 8.38). House outdoor with all three regions: 13.33 (min 12.5,
max 14.5).

Weather offset cases (same values; learned temperature offsets weather − own: N −2.0, S −1.5, W −3.5; N humidity
+9, N pressure +18 hPa from a sea-level weather pressure of 1021 hPa against a station pressure of 1003 hPa). All
regions' own sources fail:

| Direction / output | Temperature | Humidity | Pressure | AH g/m³ |
|---|---|---|---|---|
| N | 13.0 (11.0 + 2.0) | 71 (80 − 9) | 1003 | 8.04 |
| E (no region, mean offset −2.33) | 13.33 | – | – | – |
| House outdoor (mean offset) | 13.33 | – | – | – |
| N without learned offsets | 11.0 | 80 | 1021 | 7.99 |

Learning gate: N learns only while N's own value and the weather are both valid; a stale weather entity teaches
nothing.

## 6. Module `comfort` (R10)

Per-room derived values and the room's view of the outside.

```python
class Position(StrEnum): BELOW, WITHIN, ABOVE
class Relation(StrEnum): COLDER, SIMILAR, WARMER          # outside compared to inside
class Dryness(StrEnum):  DRIER, SIMILAR, MORE_HUMID       # outside AH compared to inside AH
class Trend(StrEnum):    FALLING, STEADY, RISING

def comfort_position(t, c_min, c_max, prev: Position | None) -> Position | None
def outside_relation(t_out, t_in, prev: Relation | None) -> Relation | None
def outside_dryness(ah_out, ah_in, prev: Dryness | None) -> Dryness | None
def trend(samples: TrendState, t, now, prev: Trend | None) -> tuple[Trend | None, TrendState]   # samples persisted
```

Room outputs: temperature, humidity, pressure (§4); AH and DP from the room's temperature and humidity (indoors the
sources may differ: same air, offsets learned); outside temperature and humidity (§5, room's direction); temperature
difference `t_out − t_in`; AH difference `ah_out − ah_in` (pair chain); humidity after ventilating (§3, D11); position;
relation; trend.

Rules:
1. **Position** (hysteresis 0.3 °C): `above` when `t > c_max`, kept while `t > c_max − 0.3`. `below` when
   `t < c_min`, kept while `t < c_min + 0.3`. Otherwise `within`. Invalid comfort range (`c_min ≥ c_max`): `None`.
2. **Relation** (`diff = t_out − t_in`, enter 0.5 °C, exit 0.25 °C): `colder` when `diff ≤ −0.5`, kept while
   `diff < −0.25`. `warmer` when `diff ≥ 0.5`, kept while `diff > 0.25`. Otherwise `similar`.
3. **Dryness** (`diff = ah_out − ah_in`, enter 1.0 g/m³, exit 0.5 g/m³): same shape as the relation.
4. **Trend:** least-squares slope of the room temperature over the last 60 min. Samples are kept at most one per
   minute; older ones are dropped. Less than 30 min of samples gives `None`. `rising` when `slope ≥ 0.5 K/h`, kept
   while `slope > 0.25 K/h`; `falling` mirrored; otherwise `steady`.

Position cases (comfort 20–24):

| T | Previous | Position |
|---|---|---|
| 24.0 | within | within |
| 24.1 | within | above |
| 23.8 | above | above |
| 23.7 | above | within |
| 19.9 | within | below |
| 20.2 | below | below |
| 20.3 | below | within |
| 22.0 | None | within |
| 22.0, comfort 24–20 | within | None |

Relation cases (dryness uses the same table with 1.0 / 0.5 and the labels drier / more_humid):

| diff | Previous | Relation |
|---|---|---|
| −0.4 | similar | similar |
| −0.5 | similar | colder |
| −0.3 | colder | colder |
| −0.25 | colder | similar |
| +0.6 | colder | warmer |
| +0.3 | warmer | warmer |
| +0.2 | warmer | similar |
| any, `t_out` None | any | None |

Trend cases (samples every 10 min over 60 min):

| Samples | Slope K/h | Previous | Trend |
|---|---|---|---|
| 21.0 → 21.6 in steps of 0.1 | 0.60 | steady | rising |
| 21.0 → 21.3 in steps of 0.05 | 0.30 | rising | rising |
| 21.0 → 21.24 in steps of 0.04 | 0.24 | rising | steady |
| 22.0 → 20.8 in steps of −0.2 | −1.20 | steady | falling |
| 3 samples over 20 min | – | any | None |

## 7. Module `strategy` (A1, A14, D4, D15)

```python
class Strategy(StrEnum): PREVENT_HEAT_UP, PREVENT_COOL_DOWN, NEUTRAL

@dataclass(frozen=True)
class ForecastPoint:
    start: datetime
    temperature: float          # hourly: temperature; daily: high
    temp_low: float | None      # daily only

@dataclass(frozen=True)
class ForecastBias:              # persisted
    bias_max: float | None       # learned observed − forecast, daily maximum
    bias_min: float | None       # learned observed − forecast, daily minimum
    samples: int
    day: date | None             # local date the snapshot and observations belong to
    day_f_max: float | None      # forecast for that day, taken at its first evaluation
    day_f_min: float | None
    obs_max: float | None        # observed house outdoor maximum / minimum of that day (own sensors only)
    obs_min: float | None
    covered: timedelta           # time with a valid own-sensor house outdoor value that day

def update_forecast_bias(state: ForecastBias | None, points, hourly: bool, house_outdoor: OutdoorValue,
                         now: datetime) -> ForecastBias
def daily_strategy(points: Sequence[ForecastPoint] | None, hourly: bool, now: datetime, c_min: float,
                   c_max: float, threshold: float, bias: ForecastBias | None,
                   prev: Strategy | None) -> StrategyResult   # strategy + raw and corrected f_max / f_min
```

Rules:
1. **Horizon (D4):** hourly points with `now ≤ start < now + 24 h`: `f_max` and `f_min` are their maximum and
   minimum temperature. Daily points: the entry whose local date is today: `f_max` = high, `f_min` = low. Fewer than
   12 hourly points in the horizon count as no forecast.
2. `prevent_heat_up` when `f_max > c_max + threshold`, kept while `f_max > c_max + threshold − 0.5`.
3. `prevent_cool_down` when `f_min < c_min − threshold`, kept while `f_min < c_min − threshold + 0.5`.
4. Both true: `prevent_heat_up` (D4). The cool-down risk is covered by the pre-cooling bound (D6).
5. No forecast: `None`. The recommendation then follows the neutral rules and the strategy entity is unknown.
6. **Forecast bias (D15, A14).** Rules 2 and 3 use `f_max + bias_max` and `f_min + bias_min` once at least 3 daily
   samples exist; before that the raw forecast. The strategy entity shows raw and corrected values and both biases.
7. **Learning the bias.** At the first evaluation of a local date, the forecast for that date is stored (hourly:
   maximum and minimum of the points starting within the date, at least 18 points; daily: that date's entry).
   During the day the house outdoor temperature (§5 rule 8) is tracked, but only while it comes from the regions'
   own sensors, never from the weather stage. Coverage adds the time between evaluations with such a value, each step
   capped at 10 min. At the first evaluation of the next date, if a forecast was stored and coverage is at least
   18 h, the samples are `observed − forecast` for maximum and minimum. The first sample initialises a bias; later
   ones move it by a quarter of the difference (`bias += 0.25 · (sample − bias)`, about a week of memory). Biases
   are clamped to ±5 °C. A day without stored forecast or with too little coverage gives no sample.

Cases (comfort 20–24, threshold 2):

| f_max | f_min | Previous | Strategy |
|---|---|---|---|
| 30 | 19 | neutral | prevent_heat_up |
| 26.0 | 19 | neutral | neutral |
| 25.6 | 19 | prevent_heat_up | prevent_heat_up |
| 25.5 | 19 | prevent_heat_up | neutral |
| 22 | 10 | neutral | prevent_cool_down |
| 22 | 18.4 | prevent_cool_down | prevent_cool_down |
| 22 | 18.5 | prevent_cool_down | neutral |
| 28 | 8 | neutral | prevent_heat_up |
| no forecast | | any | None |
| hourly: 24 within the next 24 h, 31 at now + 25 h | 19 | neutral | neutral |
| hourly: only 8 points in the horizon | | any | None |
| 25.0, bias +2.2 (3 samples) | 19 | neutral | prevent_heat_up (corrected 27.2) |
| 25.0, bias +2.2 (2 samples) | 19 | neutral | neutral (bias not applied yet) |
| 22, bias_min −1.5 (3 samples) | 19.0 | neutral | prevent_cool_down (corrected 17.5) |

Bias learning cases (daily maximum; the minimum works the same way):

| Day | Forecast max | Observed max | Coverage | Sample | Bias after | Samples |
|---|---|---|---|---|---|---|
| 1 | 28.0 | 30.5 | 23 h | +2.5 | 2.5 | 1 |
| 2 | 26.0 | 27.5 | 24 h | +1.5 | 2.25 | 2 |
| 3 | 30.0 | 32.0 | 24 h | +2.0 | 2.1875 | 3 |
| 4 | 25.0 | 29.0 | 17 h | – | 2.1875 | 3 |
| 5 | no forecast stored (restart at noon) | 27.0 | 24 h | – | 2.1875 | 3 |
| 1 (new) | 20.0 | 29.0 | 24 h | +9.0 | 5.0 (clamped) | 1 |

## 8. Module `window` (W2–W12, scenarios 5–8)

```python
class Level(IntEnum): CLOSED = 0; AJAR = 1; TILTED = 2; OPEN = 3

class OpenLeaves(StrEnum): NONE, LEFT, RIGHT, BOTH, UNKNOWN     # double leaf only

def contact_level(raw: str | None, kind: ContactKind, mapping: Mapping[Level, frozenset[str]] | None) -> Level | None
def window_level(config: WindowConfig, levels: Mapping[str, Level | None]) -> WindowLevel   # level, open_leaves, implausible
def debounce(raw: Level | None, prev: Debounced | None, now: datetime) -> Debounced           # 5 s
def open_since(stable: WindowLevel, debounced: Debounced, min_level: Level, prev: datetime | None,
               startup_hint: datetime | None) -> datetime | None                              # persisted
def room_windows(windows: Sequence[WindowState]) -> RoomWindows                               # W9
```

Contact mapping (W2):
- Binary sensors (device class window, door, opening, garage door): `on` → open, `off` → closed.
- Text sensors: case-insensitive exact match of the stripped state against the S8d mapping (one set of texts per
  level). A text in no set is `None`.
- `unavailable`, `unknown`, empty: `None` (W8).
- Default words for S8d, instance language plus English: closed {zu, geschlossen, verriegelt, abgeschlossen, closed,
  locked}, ajar {angelehnt, ajar}, tilted {gekippt, kipp, tilted}, open {offen, open}. Known texts of the sensor that
  match a default word are pre-assigned; the rest are offered unassigned.

Level rules (applied in this order):
1. **Leaves** (single window: one leaf). If every leaf is known: `leaf = max(leaves)`. If some leaf is unknown: the
   known maximum if it is at least tilted (a moving leaf is certain), else unknown (D9: never closed by assumption).
2. **Tilt discriminator** (optional, refiner). Reports open: the window is `open`, whatever the leaves say; if no
   known leaf is moved (above ajar) the state is flagged *implausible* (W12 last row) and `open_leaves` is unknown.
   Reports closed: a leaf level of `open` becomes `tilted` (the leaf moved but is not turned). Unknown: ignored.
3. **Handle contact** (optional, refiner). Leaf level `closed` and handle open: `ajar` (scenario 6). Leaf level above
   closed: ignored. Unknown: ignored.
4. **Pass-through** (W5): level = `min(inner, outer)`. One opening unknown: `closed` if the other is closed (no air
   path), else unknown.
5. **Ventilating** (W3): `level ≥ min_level` (default tilted; ajar does not count). Unknown level: `None`.
6. No usable contact: level `None` (W8).

Single window (M = sash contact, D = tilt discriminator, H = handle; 1 = open, 0 = closed, ? = unknown, – = not
configured):

| M | D | H | Level | Ventilating | Note |
|---|---|---|---|---|---|
| 0 | – | – | closed | no | |
| 1 | – | – | open | yes | |
| 1 | 0 | – | tilted | yes | |
| 1 | 1 | – | open | yes | |
| 0 | 1 | – | open | yes | implausible |
| 0 | – | 1 | ajar | no | scenario 6 |
| 1 | – | 1 | open | yes | handle ignored |
| ? | – | – | None | None | W8 |
| ? | 1 | – | open | yes | discriminator proves open |
| ? | 0 | – | None | None | |
| 1 | ? | – | open | yes | refiner ignored |
| 0 | – | ? | closed | no | refiner ignored |
| text „gekippt" | – | – | tilted | yes | |
| text „offen" | 0 | – | tilted | yes | discriminator caps |
| text „angelehnt" | 1 | – | open | yes | implausible |
| text „Spalt" (unmapped) | – | – | None | None | |

Double leaf (W12 plus unknown contacts; L/R leaves, D shared discriminator):

| L | R | D | Level | Open leaves |
|---|---|---|---|---|
| 0 | 0 | 0 | closed | none |
| 1 | 0 | 0 | tilted | left |
| 0 | 1 | 0 | tilted | right |
| 1 | 1 | 0 | tilted | both |
| 1 | 0 | 1 | open | left |
| 0 | 1 | 1 | open | right |
| 1 | 1 | 1 | open | both |
| 0 | 0 | 1 | open | unknown (implausible) |
| 1 | ? | 0 | tilted | left |
| 0 | ? | 0 | None | – |
| 0 | ? | 1 | open | unknown |
| 1 | 1 | ? | open | both |
| 0 | 0 | ? | closed | none |
| ? | ? | 0 | None | – |

Pass-through (scenario 7): inner 1 / outer 1 → open; 1 / 0 → closed; 0 / 1 → closed; 1 / ? → None; 0 / ? → closed;
text „gekippt" / 1 → tilted.

**Debounce and open since (W7, W10, D10).** The published level changes only after the raw level has been stable for
5 s. "Open since" is the raw time the window started ventilating; it survives level changes while ventilating, a
bounce shorter than 5 s, and unknown contacts (an unknown level keeps the previous value). It is cleared when the
published state is not ventilating.

| Time | Raw level | Published | Open since |
|---|---|---|---|
| 10:00:00 | closed | closed | – |
| 10:00:02 | tilted | closed | – |
| 10:00:07 | tilted | tilted | 10:00:02 |
| 10:05:00 | open | tilted | 10:00:02 |
| 10:05:05 | open | open | 10:00:02 |
| 10:06:00 | closed | open | 10:00:02 |
| 10:06:03 | open | open | 10:00:02 (bounce) |
| 10:20:00 | None | open | 10:00:02 |
| 10:20:05 | None | None | 10:00:02 (kept) |
| 10:30:00 | closed | None | 10:00:02 |
| 10:30:05 | closed | closed | – |

After a restart: a persisted "open since" is kept if the window is still ventilating. Without one, the latest
`last_changed` of the contacts that currently report a non-closed level (best effort; Home Assistant may reset
`last_changed` at start-up, which is why the value is persisted).

**Room aggregation (W9):** level = maximum of the windows' levels; with an unknown window: the known maximum if some
known window ventilates, else unknown. Ventilating: three-valued "any". Open since: the earliest "open since" of the
ventilating windows.

| Window A | Window B | Room level | Ventilating | Open since |
|---|---|---|---|---|
| closed | closed | closed | no | – |
| tilted since 10:00 | open since 10:05 | open | yes | 10:00 |
| closed | None | None | None | – |
| tilted since 10:00 | None | tilted | yes | 10:00 |
| ajar | None | None | None | – |
| ajar | closed | ajar | no | – |

## 9. Module `recommendation` (A2–A6, A12, scenarios 9, 11, 12)

```python
class Recommendation(StrEnum): OPEN, KEEP_OPEN, CLOSE, KEEP_CLOSED, NONE
class Goal(StrEnum): COOL, WARM, DRY, BURST, BURST_DONE

@dataclass(frozen=True)
class GoalState:                     # persisted per room
    goal: Goal | None
    started_at: datetime | None      # goal start; burst clock without windows
    pause_until: datetime | None     # after BURST_DONE, once the window is closed
    humid_guard: bool                # D8 hysteresis

def recommend(inp: RoomInput, prev: GoalState | None, now: datetime) -> tuple[RecommendationResult, GoalState]
```

`RoomInput` holds: `t_in`, `rh_in`, `t_out`, `dew_point_out`, comfort `c_min` / `c_max`, `position`, `relation`,
`dryness`, `trend`, `strategy`, `ventilating` (`None` without windows or when unknown), `ventilating_since`,
heating/cooling activity, and the options (humidity threshold, burst duration). `middle = (c_min + c_max) / 2`.

Evaluation order (the first step that decides wins):

1. **Data.** No room (window outputs only, W11): `none` / `no_room`. `t_in` or `t_out` missing: `none` / `no_data`
   (A5); the goal state is kept. Invalid comfort range: `none` / `comfort_range_invalid`.
2. **Humidity guard (D8).** `rh_after = humidity_after_ventilating(t_in, dew_point_out)`. The guard engages at
   `rh_after ≥ threshold` and releases at `rh_after < threshold − 5`. Unknown `rh_after` leaves the guard off.
3. **Thermal goal.** Cooling target: `c_min` on *prevent heat-up* days (D6), else `middle`.
   - Continue `COOL` while `t_in > target` and relation is `colder`. Continue `WARM` while `t_in < middle` and
     relation is `warmer`.
   - Start `COOL` when relation is `colder` and (position is `above`, or the day is *prevent heat-up* and
     `t_in ≥ c_min + 0.5`). Start `WARM` when relation is `warmer` and position is `below`.
   - An engaged guard ends or blocks thermal goals (reason `outside_humid`, step 5).
   - Active thermal goal: **open**, reason `pre_cool` on *prevent heat-up* days, else `cool_room`; `warm_room` for
     `WARM`.
4. **Humidity goal** (A3, A6, D7), only without a thermal goal. Needs `rh_in` and `dryness`; otherwise skipped.
   - *Harm* = (relation `colder` and (strategy *prevent cool-down* or position `below`)) or (relation `warmer` and
     (strategy *prevent heat-up* or position `above`)).
   - Start when `rh_in > threshold` and dryness is `drier`, and no pause is running. Continue while
     `rh_in > threshold − 5` and dryness is `drier`; otherwise the goal ends.
   - Without harm: `DRY`, **open**, reason `dry_room`, until the goal ends.
   - With harm: `BURST`, **open**, reason `burst_dry`. The burst clock starts when the room starts ventilating
     (`ventilating_since`), or at the goal start without windows. After the burst duration: `BURST_DONE`, **closed**,
     reason `burst_done`. With windows the pause (1 h) starts when the room stops ventilating; without windows at the
     end of the burst. During the pause: closed, reason `burst_done`. When the pause ends and the goal still
     continues, it returns to `BURST`.
   - A `DRY` goal that becomes harmful turns into `BURST` with the clock from `ventilating_since`.
5. **Closed, with a reason:** `outside_humid` if the guard blocked a thermal goal; `outside_colder` if relation is
   `colder` and (strategy *prevent cool-down* or position `below`); `outside_warmer` if relation is `warmer` and
   (strategy *prevent heat-up* or position `above`); `in_range` if position is `within`; else `no_benefit`.
6. **Window mapping:** wanted open and ventilating → `keep_open`; wanted open, otherwise → `open`; wanted closed and
   ventilating → `close`; wanted closed and not ventilating → `keep_closed`; wanted closed and ventilating `None` →
   `close` (W0: without windows only `open` or `close`).

Reasons (attribute `reason`, translated; German draft):

| Reason | German draft | Used with |
|---|---|---|
| `cool_room` | Raum zu warm, draußen kühler | open, keep_open |
| `pre_cool` | Heißer Tag erwartet, jetzt vorkühlen | open, keep_open |
| `warm_room` | Raum zu kühl, draußen wärmer | open, keep_open |
| `dry_room` | Zu feucht, draußen trockener | open, keep_open |
| `burst_dry` | Zu feucht: kurz stoßlüften | open, keep_open |
| `burst_done` | Stoßlüften beendet | close, keep_closed |
| `outside_colder` | Draußen kälter, Wärme halten | close, keep_closed |
| `outside_warmer` | Draußen wärmer, Hitze draußen halten | close, keep_closed |
| `outside_humid` | Außenluft zu feucht für diesen Raum | close, keep_closed |
| `in_range` | Raum im Wunschbereich | close, keep_closed |
| `no_benefit` | Lüften hilft gerade nicht | close, keep_closed |
| `no_data` | Werte fehlen | none |
| `comfort_range_invalid` | Wunschbereich ungültig (Minimum über Maximum) | none |
| `no_room` | Fenster ohne Raum | none |

Cases. Comfort 20–24 (middle 22), humidity threshold 60 %, burst 10 min, pause 1 h, room humidity 50 % unless stated. Position, relation and dryness
follow from the values (§6) with the previous state of the row above.

Scenario 11, neutral day:

| Time | T in | T out | Window | Goal before | Recommendation | Reason | Goal after |
|---|---|---|---|---|---|---|---|
| 10:00 | 24.6 | 19.0 | closed | – | open | cool_room | COOL |
| 10:10 | 24.4 | 19.0 | open | COOL | keep_open | cool_room | COOL |
| 10:40 | 23.9 | 19.0 | open | COOL | keep_open | cool_room | COOL |
| 11:20 | 22.0 | 19.0 | open | COOL | close | in_range | – |
| 11:30 | 22.3 | 19.0 | closed | – | keep_closed | in_range | – |
| alt. 11:00 | 23.0 | 22.9 | open | COOL | close | in_range | – |

Scenario 9, bathroom on a *prevent cool-down* day (21 °C, outside 3 °C / 85 %, AH 5.05 vs 12.43 at 68 %):

| Time | RH in | Window | Recommendation | Reason | Goal after | Cooling-down warning |
|---|---|---|---|---|---|---|
| 07:00 | 68 | closed | open | burst_dry | BURST | off |
| 07:02 | 67 | opens (ventilating since 07:02) | keep_open | burst_dry | BURST | off |
| 07:11 | 63 | open | keep_open | burst_dry | BURST | off |
| 07:12 | 62 | open | close | burst_done | BURST_DONE | on |
| 07:13 | 62 | closed | keep_closed | burst_done | BURST_DONE, pause until 08:13 | off |
| 08:00 | 63 | closed | keep_closed | burst_done | BURST_DONE | off |
| 08:13 | 63 | closed | open | burst_dry | BURST | off |
| 08:40 | 55 | closed | keep_closed | outside_colder | – | off |

Other cases (window closed unless stated):

| # | Strategy | T in | RH in | T out | Outside RH | Before | Recommendation | Reason |
|---|---|---|---|---|---|---|---|---|
| 1 | cool-down | 21.0 | 50 | 5 | 80 | – | keep_closed | outside_colder |
| 2 | cool-down | 25.0 | 50 | 5 | 80 | – | open | cool_room (D5) |
| 3 | heat-up | 22.0 | 50 | 16 | 70 | – | open | pre_cool |
| 4 | heat-up | 20.0, open | 50 | 16 | 70 | COOL | close | in_range (D6) |
| 5 | heat-up | 22.0, open | 50 | 28 | 40 | – | close | outside_warmer |
| 6 | neutral | 19.0 | 50 | 23 | 40 | – | open | warm_room |
| 7 | neutral | 19.0 | 50 | 10 | 70 | – | keep_closed | outside_colder |
| 8 | neutral | 25.0 | 50 | 27 | 40 | – | keep_closed | outside_warmer |
| 9 | neutral | 25.0 | 50 | 24.8 | 50 | – | keep_closed | no_benefit |
| 10 | neutral | 22.0 | 65 | 21.8 | 40 | – | open | dry_room |
| 11 | neutral | 22.0, open | 58 | 21.8 | 40 | DRY | keep_open | dry_room |
| 12 | neutral | 22.0, open | 55 | 21.8 | 40 | DRY | close | in_range |
| 13 | neutral | 20.0 (cellar) | 65 | 24 | 70 | – | keep_closed | in_range (scenario 12) |
| 14 | neutral | 19.9 (cellar) | 65 | 24 | 70 | – | keep_closed | outside_humid (D8, RH after 89.9 %) |
| 15 | neutral, no windows | 24.6 | 50 | 19 | 70 | – | open | cool_room |
| 16 | cool-down, no windows | 21.0 | 50 | 5 | 80 | – | close | outside_colder |
| 17 | any | 22.0 | 50 | None | – | any | none | no_data |
| 18 | none (no forecast) | 24.6 | 50 | 19 | 70 | – | open | cool_room |
| 19 | neutral, comfort 24–20 | 22.0 | 50 | 19 | 70 | – | none | comfort_range_invalid |

Case 14 also guards cooling: neutral, room 26 °C, outside 20 °C / 70 % starts `COOL` (RH after 48.7 %); as the room
cools, RH after reaches 61.9 % at 22 °C and the guard ends the goal before the middle (closed, `outside_humid`).

**Warnings (A4, D12).** Only with windows. `ventilating_for = now − ventilating_since`.

- *Cooling down*: ventilating for at least the burst duration, strategy *prevent cool-down*, relation `colder`, and
  the room does not want the window open.
- *Heating up*: ventilating for at least the burst duration, strategy *prevent heat-up*, relation `warmer` or trend
  `rising`, and the room does not want the window open.
- Ventilating `None`: both `None`. House-level variants: three-valued "any" over rooms (H4).

| Strategy | Relation | Trend | Ventilating for | Wanted | Cooling down | Heating up |
|---|---|---|---|---|---|---|
| cool-down | colder | – | 12 min | closed | on | off |
| cool-down | colder | – | 8 min | closed | off | off |
| cool-down | colder | – | 30 min | open (cool_room) | off | off |
| heat-up | warmer | – | 15 min | closed | off | on |
| heat-up | colder | rising | 15 min | closed | off | on |
| heat-up | colder | rising | 15 min | open (pre_cool) | off | off |
| neutral | colder | – | 60 min | closed | off | off |
| any | any | any | not ventilating | any | off | off |
| any | any | any | None | any | None | None |

**Open while heating or cooling (A12).** On when the room ventilates for at least the burst duration and one of its
heating or cooling devices (R15) is active. Active: `hvac_action` in {heating, preheating, cooling, drying}; without
`hvac_action`: `hvac_mode` in {heat, cool, heat_cool, auto, dry}. A device without either is ignored. The entity
exists only with windows and devices.

| Device | Ventilating for | Open while conditioning |
|---|---|---|
| action heating | 12 min | on |
| action idle | 12 min | off |
| no action, mode heat | 12 min | on |
| no action, mode off | 12 min | off |
| action heating | 5 min | off |
| unavailable, other device idle | 12 min | off |
| action cooling | ventilating None | None |

## 10. Module `cover` (SH1, SH2, SH4, D16)

Recommends what to do with a window's cover: protect against sun and heat by day, keep warmth in at night, let the
sun in when its warmth is welcome. It never moves a cover. Automations act on it and filter by reason, for example
"sun protection only", so there is no setting for it (P4).

```python
class CoverAdvice(StrEnum): CLOSE, KEEP_CLOSED, OPEN, KEEP_OPEN, NONE

@dataclass(frozen=True)
class CoverState:                # persisted per window
    wanted: Literal["closed", "open"] | None
    reason: str | None
    since: datetime | None
    relation: Relation | None    # window's outside temperature vs room (§6 rule 2)
    heat_risk: bool

def cover(inp: CoverInput, prev: CoverState | None, now: datetime) -> tuple[CoverResult, CoverState]
```

`CoverInput`: sun azimuth and elevation (`sun.sun`), cloud coverage (weather attribute, optional), facing azimuth
(from the window's direction N 0°, E 90°, S 180°, W 270°, or the exact degrees, SH4), room temperature, comfort
range, position, outside temperature of the window's direction (§5), strategy, the window's debounced level (§8),
and the cover state (closed / not closed / unknown / no cover).

Rules:
1. No room: `none` / `no_room`. No sun position or no room temperature: `none` / `no_data`.
2. **Relation:** the window's outside temperature against the room temperature, with the hysteresis of §6 rule 2
   (a window can face another direction than its room, W1).
3. **Gain welcome:** position `below`, or outside temperature below `c_min`. Then the cover is never closed by day
   (SH1).
4. **Night** (sun elevation below 0°): wanted closed, reason `insulate`, when the relation is `colder` and (strategy
   *prevent cool-down* or position `below`). Otherwise `none` / `night`.
5. **Day**, the first matching rule decides:
   - *Sun on the window:* elevation ≥ 10°, angular difference between sun azimuth and facing ≤ 60° (with
     wrap-around), cloud coverage ≤ 70 % when known.
   - *Heat risk:* strategy *prevent heat-up*, or room temperature ≥ `c_max − 0.5` (kept while ≥ `c_max − 1.0`).

   | # | Condition | Wanted | Reason |
   |---|---|---|---|
   | a | sun on the window and gain welcome | open | `solar_gain` |
   | b | sun on the window and heat risk | closed | `sun_heat` |
   | c | strategy *prevent heat-up*, relation `warmer`, gain not welcome | closed | `heat_barrier` |
   | d | sun on the window | open | `no_heat_risk` |
   | e | otherwise | open | `no_sun` |
6. **Open window guard:** wanted closed while the window's level is `open` gives `none` / `window_open` (a closing
   cover could lock someone out at a door). Tilted, ajar and unknown levels do not block.
7. **Hold:** the wanted state changes only after the previous one was held for 15 min; a held state keeps its reason.
   Changes to and from `none` are immediate.
8. **Cover state (SH2):** closed when `current_position ≤ 50`, or state `closed` without a position; `opening`,
   `closing` and unavailable are unknown. Wanted closed: closed → `keep_closed`, else `close`. Wanted open: not
   closed → `keep_open`, else `open`. No cover or unknown state: `close` or `open` only.
9. **House level:** "any cover to close" is `True` if any window wants its cover closed (any reason; the attribute
   lists windows and reasons), else `False`.

Reasons (attribute `reason`, translated; German draft):

| Reason | German draft |
|---|---|
| `sun_heat` | Sonne auf dem Fenster, Hitze draußen halten |
| `heat_barrier` | Draußen heißer, Hitze draußen halten |
| `insulate` | Nachts kalt, Wärme drinnen halten |
| `solar_gain` | Sonnenwärme ist willkommen |
| `no_heat_risk` | Sonne, aber keine Überhitzung |
| `no_sun` | Keine Sonne auf dem Fenster |
| `night` | Nacht, kein Grund zum Schließen |
| `window_open` | Fenster ist offen |
| `no_data` | Werte fehlen |
| `no_room` | Fenster ohne Raum |

Cases (window facing south 180°, comfort 20–24, held long enough, window closed and no cover unless stated):

| Azimuth | Elevation | Clouds | Strategy | T room | T out | Window / cover | Advice | Reason |
|---|---|---|---|---|---|---|---|---|
| 180 | 40 | 20 | heat-up | 22.0 | 25 | – | close | sun_heat |
| 180 | 40 | 20 | heat-up | 22.0 | 25 | cover closed | keep_closed | sun_heat |
| 180 | 40 | 20 | heat-up | 22.0 | 25 | cover opening | close | sun_heat |
| 180 | 40 | 20 | heat-up | 22.0 | 25 | window tilted | close | sun_heat |
| 180 | 40 | 20 | heat-up | 22.0 | 25 | window open (door) | none | window_open |
| 90 | 40 | 0 | heat-up | 22.0 | 25 | – | close | heat_barrier |
| 90 | 40 | 0 | heat-up | 22.0 | 20 | – | open | no_sun |
| 245 | 30 | 20 | neutral | 22.0 | 25 | cover open | keep_open | no_sun (65° off) |
| 180 | 8 | 0 | neutral | 22.0 | 25 | – | open | no_sun |
| 180 | 40 | 90 | neutral | 22.0 | 25 | – | open | no_sun |
| 180 | 40 | 20 | neutral | 22.0 | 25 | – | open | no_heat_risk |
| 180 | 40 | 20 | neutral | 23.6 | 25 | – | close | sun_heat |
| 180 | 40 | 20 | heat-up | 19.5 | 25 | – | open | solar_gain |
| 180 | 40 | 20 | neutral | 23.6 | 15 | – | open | solar_gain |
| 350, window facing north | 15 | 0 | heat-up | 22.0 | 25 | – | close | sun_heat (wrap-around) |
| – | −10 | – | cool-down | 21.0 | 5 | – | close | insulate |
| – | −10 | – | cool-down | 21.0 | 5 | cover closed | keep_closed | insulate |
| – | −10 | – | neutral | 19.5 | 10 | – | close | insulate (room below) |
| – | −10 | – | neutral | 22.0 | 15 | – | none | night |
| – | −10 | – | heat-up | 25.0 | 18 | – | none | night |
| sun leaves at 10:10, closed since 10:00 | | | neutral | 23.6 | 25 | – | close | sun_heat (held) |
| sun leaves at 10:15, closed since 10:00 | | | neutral | 23.6 | 25 | – | open | no_sun |
| no sun entity | | | | | | – | none | no_data |

## 11. Module `prefill` (R3, R6, R14, R15, S2)

Called by the flows and by the new-source listener (R14). Input is a registry snapshot built by the adapter:

```python
@dataclass(frozen=True)
class EntityInfo:
    entity_id: str
    name: str
    domain: str                  # sensor, climate, binary_sensor, light, ...
    device_class: str | None
    platform: str
    category: str | None         # None, "diagnostic", "config"
    device_id: str | None
    area_id: str | None          # effective area: entity area, else device area
    value: float | None          # current value in the metric's unit (climate: current_temperature)
    has_current_humidity: bool   # climate only

def classify(entity: EntityInfo, device_entities: Sequence[EntityInfo], metric: Metric,
             scope: Scope) -> Tier | Exclusion | None      # None: never offered (own entity)
def suggest_sources(area_id, entities, metric, scope) -> Suggestion   # ordered sources + excluded with reasons
def follow_devices(temperature_sources, entities, metric) -> list[str]  # R3 "follow"
def suggest_metric_list(temperature_sources, area_id, entities, metric) -> list[str]  # [] means follow
def suggest_climate_devices(area_id, entities) -> list[str]           # R15
def propose_rooms(areas: Sequence[AreaInfo], outside_words: frozenset[str]) -> RoomProposal  # S2
```

Classification of a temperature candidate (sensor with device class temperature, or a `climate` entity). The first
matching rule decides:

| # | Rule | Result | Preview reason (S4) |
|---|---|---|---|
| 1 | Platform is `climate_hub` | never offered | – |
| 2 | Category diagnostic or config | excluded `diagnostic` | „Gerätetemperatur" |
| 3 | Platform is a helper (template, min_max, statistics, filter, derivative, integration, trend, threshold, compensation, group, thermal_comfort) | excluded `helper` | „abgeleiteter Wert" |
| 4 | No device | excluded `no_device` | „ohne Gerät" |
| 5 | `climate` entity (rooms only) | tier 3; `implausible` if its value is outside the room range | – |
| 6 | Device has a non-diagnostic binary sensor of class window, door, opening or garage door | excluded `contact` | „Nebenwert eines Kontakts" |
| 7 | Device has a non-diagnostic binary sensor of class motion, occupancy or presence | excluded `motion` | „Nebenwert eines Bewegungsmelders" |
| 8 | Device has a non-diagnostic entity of an actuator domain (light, switch, cover, climate, fan, media_player, lock, vacuum, humidifier, water_heater, valve, siren) | excluded `secondary` | „Nebenwert eines Geräts" |
| 9 | Device has more than one temperature sensor (not counting diagnostic and helper entities) | excluded `several_temperatures` | „mehrere Temperaturen am Gerät" |
| 10 | Value known and outside the plausible range (room 8–40 °C, region −40–60 °C) | excluded `implausible` | „kein Raumwert" |
| 11 | Device has a non-diagnostic humidity sensor | tier 1 | – |
| 12 | Otherwise | tier 2 | – |

Rules:
- Pre-filled: entities whose effective area is the object's area, in tier order, then by name, then by entity ID.
  Entities without an area are offered in the picker (U6) but never pre-filled.
- Regions use the same rules with the region range and without tier 3 (a `climate` entity in an outdoor area is
  excluded as `secondary`).
- Humidity and pressure candidates use rules 1–4 and 6–8, plausible ranges 0–100 % and 800–1100 hPa, tier 1 for
  devices that also measure temperature, tier 2 otherwise, and (humidity only) tier 3 for `climate` entities with
  `current_humidity`.
- **Follow (R3):** for each temperature source in order: a `climate` entity contributes itself if it has
  `current_humidity` (humidity only); a sensor contributes its device's humidity (or pressure) sensors that pass
  rules 1–3, by entity ID. Duplicates are dropped. The adapter resolves "follow" at runtime when the registries
  change (N5).
- **Creation (R3):** if follow yields nothing for a metric, the stored list is pre-filled from the area's candidates
  of that metric; otherwise it is stored empty (follow).
- **New source (R14):** an entity in the area of a room or region is reported when it classifies as tier 1 or 2
  (rooms: also 3), is not in any of the object's lists, and is not dismissed.
- **Heating and cooling devices (R15):** all `climate` entities in the area except own entities, by name.
- **Rooms (S2):** areas with a temperature sensor or a `climate` entity. Pre-checked: not on a floor whose name
  contains an outside word (case-insensitive); checked if it has a `climate` entity; checked if it is on a floor;
  otherwise not checked. Sorted by floor level (floors without level after), then floor name, then area name; areas
  without a floor last. Outside words come from the translations (S2).

Cases, kitchen (area Küche):

| Entity | Situation | Result |
|---|---|---|
| Climate sensor T/H/P | one temperature + humidity + pressure | tier 1 |
| Air meter T/H | one temperature + humidity | tier 1 |
| Probe T only (ESPHome) | one temperature, diagnostic restart button | tier 2 |
| Fridge sensor | value 6.9 °C | `implausible` |
| 3D printer | nozzle, bed and chamber temperature on one device | `several_temperatures` (each) |
| Window contact with temperature | device has a window binary sensor | `contact` |
| Motion sensor with temperature | device has a motion binary sensor | `motion` |
| Smart plug | temperature is diagnostic | `diagnostic` |
| Heating setpoint template | platform template | `helper` |
| Dew point from thermal_comfort | platform thermal_comfort | `helper` |
| Sensor without device | | `no_device` |
| Thermostat | `climate` entity | tier 3 |
| Air conditioner | climate + outdoor temperature sensor (18 °C) | climate: tier 3; sensor: `secondary` |
| Climate Hub's own temperature | | not offered |
| Climate sensor in no area | | offered, not pre-filled |

Pre-filled order (scenario 1): Air meter, Climate sensor (tier 1, by name), Probe (tier 2), Thermostat (tier 3).

Follow cases: temperature [Climate sensor, Air meter, Thermostat with `current_humidity`] → humidity [Climate sensor
humidity, Air meter humidity, Thermostat]; pressure [Climate sensor pressure]. Temperature [sensor without device] →
follow yields nothing → humidity list pre-filled from the area's humidity candidates.

S2 cases (outside words contain „außen", „garten"):

| Area | Floor | Climate entity | Pre-checked |
|---|---|---|---|
| Wohnzimmer | Erdgeschoss | yes | yes |
| Bad | Erdgeschoss | no | yes |
| Garten | Außen | no | no |
| Terrasse | Außenbereich | no | no |
| Straße | – | no | no |
| Werkstatt | – | yes | yes |

## 12. Module `house` (H4, H5, O7)

```python
def indoor_average(rooms: Sequence[float | None]) -> HouseValue      # mean, min, max of valid room temperatures
def any_of(flags: Sequence[bool | None]) -> bool | None               # three-valued
def outages(sources: Sequence[Reading], state: OutageState | None, now: datetime,
            delay: timedelta) -> tuple[list[Outage], OutageState]     # persisted
```

Rules:
1. Indoor average: mean of the rooms with a value; min and max as attributes; no room with a value: `None`.
2. House outdoor: §5 rule 8.
3. "Any room" flags (cooling down, heating up, open while conditioning): `any_of` over rooms that have the entity.
4. **Outages (H5):** each configured source has an "invalid since" timestamp, set when it is first seen invalid and
   cleared when it is valid again. An outage is reported when `now − invalid_since ≥ delay` (default 6 h). The
   adapter groups outages by object and device for the repair text and names the active fallback (S11). The state
   is persisted, so a restart does not restart the 6 hours.

| Room values | Average | Min | Max |
|---|---|---|---|
| 21.0, 22.0, 23.5 | 22.17 | 21.0 | 23.5 |
| 21.0, None | 21.0 | 21.0 | 21.0 |
| None, None | None | – | – |

| Flags | any_of |
|---|---|
| False, False | False |
| False, True, None | True |
| False, None | None |
| (none) | None |

| Source invalid since | Now | Delay | Outage |
|---|---|---|---|
| 06:00 | 11:59 | 6 h | no |
| 06:00 | 12:00 | 6 h | yes |
| 06:00, valid again at 10:00 | 12:00 | 6 h | no (cleared) |

## 13. Constants

| Constant | Value | Configurable | Source |
|---|---|---|---|
| Maximum age of a measurement | 40 min | hub option, room/region override | Q5 |
| Maximum age of the weather entity | 2 h | no | O5, D14 |
| Burst duration | 10 min | hub option | Q5 |
| Humidity threshold | 60 % | hub option | Q5 |
| Humidity release | threshold − 5 points | no | A6 |
| Repair delay | 6 h | hub option | Q5 |
| Pause after a burst | 1 h | no | D7 |
| Outside relation enter / exit | 0.5 / 0.25 °C | no | A6 |
| Dryness enter / exit | 1.0 / 0.5 g/m³ | no | A3 |
| Comfort position hysteresis | 0.3 °C | no | R10 |
| Pre-cooling start above comfort minimum | 0.5 °C | no | D6 |
| Strategy hysteresis | 0.5 °C | no | A1 |
| Trend window / minimum span | 60 / 30 min | no | R10 |
| Trend enter / exit | 0.5 / 0.25 K/h | no | R10 |
| Offset time constant / sample cap | 8 h / 30 min | no | R7, D1 |
| Offset learned after | 1 h paired | no | R7 |
| Offset glide | 60 min | no | D1 |
| Contact debounce | 5 s | no | W10 |
| Weather offsets | same learner as source offsets (8 h / 30 min) | no | O5, D15 |
| Forecast bias: memory / samples before use / clamp | 0.25 per day / 3 / ±5 °C | no | A14, D15 |
| Forecast bias: day coverage / hourly points per day / coverage step cap | 18 h / 18 / 10 min | no | A14, D15 |
| Sun on window | elevation ≥ 10°, ±60°, clouds ≤ 70 % | no | SH1 |
| Night (cover) | sun elevation below 0° | no | SH1, D16 |
| Heat risk near comfort maximum enter / exit | 0.5 / 1.0 °C below | no | SH1 |
| Cover hold | 15 min | no | SH1 |
| Cover counts as closed | position ≤ 50 % | no | SH2 |
| Plausible values at setup | room 8–40 °C, region −40–60 °C, 0–100 %, 800–1100 hPa | no | R6 |
| Comfort range defaults | 20 / 24 °C, threshold 2 °C | number entities | H2, D14 |

## 14. Not in this spec

Deferred with their requirements: air quality (A7), forecast extras (A8), cross-ventilation (A9), best window
(A10), time to close (A11), mould risk (R12), offsets between regions (O8), region preference (O9), sun-exposure
plausibility (O10), sun-intensity sensor (SH3). Their inputs fit the interfaces above, so adding them later needs no
migration.

Adapter concerns, specified in the build tasks, not here: unit conversion, reading `last_reported`, forecast
subscription (`weather.get_forecasts`), state listeners and the 60 s tick, the 5 s re-evaluation after a contact
change, `Store` persistence, area sync (R11), repair issues (R14, H5, W11).

## 15. Build order

One Sonnet implementer per module, each with its tests, in this order (later modules use earlier ones):
`const` + `psychro` → `sources` → `outdoor` → `comfort` → `strategy` → `window` → `recommendation` → `cover` →
`prefill` → `house`. Each module is done when its table cases pass, `ruff check` is clean, and it imports nothing from
`homeassistant`.
