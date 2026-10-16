"""Engine (docs/integration.md §4): scenarios 2 to 7 and 9 to 12, the logic §14
contract, isolation, windows, warnings and covers. Hand-built models and snapshots,
no Home Assistant."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from custom_components.climate_hub.logic import engine
from custom_components.climate_hub.logic.cover import (
    CoverAdvice,
    CoverPosition,
    CoverReason,
)
from custom_components.climate_hub.logic.engine import (
    Comfort,
    Contact,
    EngineState,
    Forecast,
    Snapshot,
    evaluate,
)
from custom_components.climate_hub.logic.model import (
    RegionModel,
    RoomModel,
    WindowModel,
    build_house,
    parse_region,
    parse_room,
    parse_settings,
    parse_window,
)
from custom_components.climate_hub.logic.outdoor import (
    Direction,
    OutdoorReason,
    WeatherReadings,
)
from custom_components.climate_hub.logic.psychro import absolute_humidity
from custom_components.climate_hub.logic.recommendation import (
    ClimateDevice,
    Reason,
    Recommendation,
)
from custom_components.climate_hub.logic.sources import (
    Metric,
    Reading,
    Stage,
    Status,
)
from custom_components.climate_hub.logic.strategy import ForecastPoint, Strategy
from custom_components.climate_hub.logic.window import Level, OpenLeaves

N, E, S, W = Direction.N, Direction.E, Direction.S, Direction.W
T, H, P = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE
START = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
COMFORT = Comfort(20.0, 24.0, 2.0)
SETTINGS = parse_settings({})


def at(minutes: float = 0) -> datetime:
    return START + timedelta(minutes=minutes)


def room(
    room_id: str,
    temperature: list[str],
    side: Direction | None = None,
    humidity: list[str] | None = None,
    followed: dict[Metric, list[str]] | None = None,
    devices: list[str] | None = None,
) -> RoomModel:
    data = {
        "area": f"area_{room_id}",
        "side": side or "none",
        "temperature": temperature,
        "humidity": humidity or [],
        "climate_devices": devices or [],
    }
    return parse_room(room_id, data, SETTINGS, followed or {})


def region(
    region_id: str,
    direction: Direction,
    temperature: list[str],
    humidity: list[str] | None = None,
) -> RegionModel:
    data = {
        "area": f"area_{region_id}",
        "direction": direction,
        "temperature": temperature,
        "humidity": humidity or [],
    }
    return parse_region(region_id, data, SETTINGS, {})


def window(window_id: str, in_room: str | None, **data) -> WindowModel:
    """A single-leaf window in the area of `in_room` (None: an area without a room)."""
    return parse_window(
        window_id,
        {
            "area": f"area_{in_room}" if in_room else "area_nowhere",
            "type": "single",
            "name": "Fenster",
            "leaf": f"binary_sensor.{window_id}",
            **data,
        },
    )


def house(rooms=(), regions=(), weather: str | None = "weather.home", windows=()):
    return build_house(
        SETTINGS,
        weather,
        {r.id: r for r in rooms},
        {r.id: r for r in regions},
        {w.id: w for w in windows},
    )


def weather_readings(now, t=11.0, h=80.0, p=1021.0) -> WeatherReadings:
    return WeatherReadings(
        *(Reading("weather.home", v, Status.OK, now) for v in (t, h, p))
    )


def snapshot(
    now,
    values,
    *,
    weather=True,
    forecast=None,
    contacts=None,
    climate=None,
    covers=None,
    sun=(None, None),
) -> Snapshot:
    """`values` maps (entity, metric) to a float, a Status or a ready Reading.

    `contacts` maps an entity to its raw state or a ready `Contact`; `sun` is
    (azimuth, elevation)."""
    readings = {}
    for (entity_id, metric), value in values.items():
        if isinstance(value, Reading):
            readings[entity_id, metric] = value
        elif isinstance(value, Status):
            readings[entity_id, metric] = Reading(entity_id, None, value, now)
        else:
            readings[entity_id, metric] = Reading(entity_id, value, Status.OK, now)
    return Snapshot(
        readings=readings,
        contacts={
            entity_id: raw if isinstance(raw, Contact) else Contact(raw, None)
            for entity_id, raw in (contacts or {}).items()
        },
        climate=climate or {},
        covers=covers or {},
        weather=weather_readings(now) if weather is True else weather or None,
        clouds=None,
        forecast=forecast,
        sun_azimuth=sun[0],
        sun_elevation=sun[1],
    )


def run(model, values, state, now, comfort=COMFORT, **kwargs):
    return evaluate(model, snapshot(now, values, **kwargs), state, comfort, now)


OWN = {N: (13.0, 71.0), S: (12.5, 76.0), W: (14.5, 65.0)}


def outside(failing=()):
    """Own readings of the regions N, S, W; `failing` ones are unavailable."""
    values = {}
    for direction, (t, h) in OWN.items():
        bad = direction in failing
        values[f"sensor.{direction}_t", T] = Status.UNAVAILABLE if bad else t
        values[f"sensor.{direction}_h", H] = Status.UNAVAILABLE if bad else h
    return values


def three_regions():
    return [
        region(f"g_{d}", d, [f"sensor.{d}_t"], [f"sensor.{d}_h"]) for d in (N, W, S)
    ]


# Scenario 2: thermostat offset


def test_thermostat_takes_over_without_a_jump_and_hands_back():
    model = house([room("r1", ["sensor.room", "climate.thermo"])], weather=None)
    state = EngineState.empty()
    values = []
    for step in range(16):
        now = at(30 * step)
        sensor_down = 8 <= step < 13  # two hours without the room sensor
        values.append(
            run(
                model,
                {
                    ("sensor.room", T): Status.UNAVAILABLE if sensor_down else 21.0,
                    ("climate.thermo", T): 22.0
                    + (0.1 * (step - 8) if sensor_down else 0),
                },
                state,
                now,
                weather=None,
            )
        )
        state = values[-1][1]

    temperatures = [result.rooms["r1"].temperature for result, _ in values]
    assert [t.stage for t in temperatures[:8]] == [Stage.PRIMARY] * 8
    for t in temperatures[8:13]:
        assert t.stage is Stage.FALLBACK
        assert t.source == "climate.thermo"
        assert t.offset == pytest.approx(1.0)
        assert t.reason is Status.UNAVAILABLE
    # 21.0 before, thermostat 22.0 corrected by its learned +1.0: no visible jump
    assert temperatures[8].value == pytest.approx(21.0)
    steps = [b.value - a.value for a, b in pairwise(temperatures[7:13])]
    assert max(abs(s) for s in steps) < 0.15
    assert temperatures[13].stage is Stage.PRIMARY
    assert temperatures[13].value == 21.0


# Scenarios 3 and 4: outdoor chain per side


def test_north_fails_over_neighbour_opposite_and_weather():
    model = house([room("r1", ["sensor.room"], N)], three_regions())
    state = EngineState.empty()
    expected = [
        ((), 13.0, Stage.PRIMARY, (N,)),
        ((N,), 14.5, Stage.NEIGHBOUR, (W,)),  # E is not configured
        ((N, W), 12.5, Stage.OPPOSITE, (S,)),
        ((N, W, S), 13.0, Stage.WEATHER, ()),  # 11.0 - learned offset (-2.0)
    ]
    for step, (failing, value, stage, regions) in enumerate(expected):
        result, state = run(
            model, {("sensor.room", T): 21.0, **outside(failing)}, state, at(10 * step)
        )
        outdoor = result.rooms["r1"].outdoor.temperature
        assert (outdoor.value, outdoor.stage, outdoor.regions) == (
            pytest.approx(value),
            stage,
            regions,
        )
        assert result.regions["g_n"].values.temperature == outdoor
        assert not result.failures
    assert outdoor.offset == pytest.approx(-2.0)

    result, state = run(
        model,
        {("sensor.room", T): 21.0, **outside((N, W, S))},
        state,
        at(40),
        weather=None,
    )
    assert result.rooms["r1"].outdoor.temperature.stage is Stage.NONE
    assert result.rooms["r1"].recommendation.reason is Reason.NO_DATA


def test_first_region_alone_skips_straight_to_weather():
    model = house([room("r1", ["sensor.room"], N)], [three_regions()[0]])
    state = EngineState.empty()
    result, state = run(model, {("sensor.room", T): 21.0, **outside()}, state, at(0))
    assert result.rooms["r1"].outdoor.temperature.stage is Stage.PRIMARY

    result, _ = run(model, {("sensor.room", T): 21.0, **outside((N,))}, state, at(10))
    outdoor = result.rooms["r1"].outdoor.temperature
    assert (outdoor.stage, outdoor.regions) == (Stage.WEATHER, ())
    assert outdoor.value == pytest.approx(13.0)

    # nothing learned yet: the raw weather value
    result, _ = run(
        model,
        {("sensor.room", T): 21.0, **outside((N,))},
        EngineState.empty(),
        at(0),
    )
    outdoor = result.rooms["r1"].outdoor.temperature
    assert (outdoor.value, outdoor.stage, outdoor.offset) == (11.0, Stage.WEATHER, 0.0)


# Scenario 11: no ping-pong


@pytest.mark.parametrize(
    ("steps", "wanted"),
    [
        pytest.param(
            [(24.6, 19.0), (23.9, 19.0), (22.5, 19.0), (21.9, 19.0)],
            [True, True, True, False],
            id="closes_at_22",
        ),
        pytest.param(
            [(24.6, 19.0), (23.9, 25.0)],
            [True, False],
            id="closes_when_outside_stops_being_cooler",
        ),
    ],
)
def test_no_ping_pong(steps, wanted):
    model = house([room("r1", ["sensor.room"], S)], [region("g_s", S, ["sensor.out"])])
    state = EngineState.empty()
    for step, ((t_in, t_out), want) in enumerate(zip(steps, wanted, strict=True)):
        result, state = run(
            model,
            {("sensor.room", T): t_in, ("sensor.out", T): t_out},
            state,
            at(step),
            weather=None,
        )
        recommendation = result.rooms["r1"].recommendation
        assert recommendation.wanted_open is want
        assert recommendation.recommendation is (
            Recommendation.OPEN if want else Recommendation.CLOSE
        )


# Scenario 12: summer cellar


def test_summer_cellar_is_not_ventilated_to_dry():
    model = house(
        [room("cellar", ["sensor.cellar_t"], S, ["sensor.cellar_h"])],
        [region("g_s", S, ["sensor.out_t"], ["sensor.out_h"])],
    )
    values = {
        ("sensor.cellar_t", T): 20.0,
        ("sensor.cellar_h", H): 75.0,
        ("sensor.out_t", T): 24.0,
        ("sensor.out_h", H): 70.0,
    }
    state = EngineState.empty()
    for step in range(3):
        result, state = run(
            model, values, state, at(5 * step), Comfort(21.0, 25.0, 2.0), weather=None
        )
        cellar = result.rooms["cellar"]
        assert cellar.humidity_after_ventilating == pytest.approx(89.3, abs=0.1)
        assert cellar.recommendation.recommendation is Recommendation.CLOSE
        assert cellar.recommendation.reason is Reason.OUTSIDE_HUMID
        assert cellar.recommendation.wanted_open is False


# Rooms: no side, followed humidity, strategy


def test_room_without_side_has_no_outdoor_values():
    model = house([room("r1", ["sensor.room"])], three_regions())
    result, _ = run(
        model, {("sensor.room", T): 21.0, **outside()}, EngineState.empty(), at()
    )
    r1 = result.rooms["r1"]
    assert r1.temperature.value == 21.0
    assert r1.outdoor.temperature.reason is OutdoorReason.NO_SIDE
    assert r1.temperature_difference is None
    assert r1.relation is None
    assert r1.recommendation.reason is Reason.NO_SIDE
    assert result.house.indoor.value == 21.0


def test_room_with_followed_humidity_uses_the_followed_sensor():
    parsed = room("r1", ["sensor.room"], followed={H: ["sensor.followed_h"]})
    assert parsed.sources[H] == ("sensor.followed_h",)
    result, state = run(
        house([parsed], weather=None),
        {("sensor.room", T): 21.0, ("sensor.followed_h", H): 55.0},
        EngineState.empty(),
        at(),
        weather=None,
    )
    r1 = result.rooms["r1"]
    assert r1.humidity.source == "sensor.followed_h"
    assert r1.absolute_humidity == pytest.approx(absolute_humidity(21.0, 55.0))
    assert r1.dew_point is not None
    assert set(state.rooms["r1"].sources) == {T, H, P}


def test_hot_forecast_prevents_heat_up_and_pre_cools():
    model = house([room("r1", ["sensor.room"], S)], [region("g_s", S, ["sensor.out"])])
    forecast = Forecast(
        tuple(ForecastPoint(at(60 * i), 18.0 + i / 2) for i in range(24)), hourly=True
    )
    result, state = run(
        model,
        {("sensor.room", T): 23.0, ("sensor.out", T): 15.0},
        EngineState.empty(),
        at(),
        weather=None,
        forecast=forecast,
    )
    assert result.house.strategy.strategy is Strategy.PREVENT_HEAT_UP
    assert state.hub.strategy is Strategy.PREVENT_HEAT_UP
    assert result.rooms["r1"].recommendation.reason is Reason.PRE_COOL


def test_removed_objects_leave_the_state():
    both = house([room("r1", ["sensor.a"]), room("r2", ["sensor.b"])])
    values = {("sensor.a", T): 21.0, ("sensor.b", T): 22.0}
    _, state = run(both, values, EngineState.empty(), at(), weather=None)
    assert set(state.rooms) == {"r1", "r2"}
    _, state = run(
        house([room("r1", ["sensor.a"])]), values, state, at(1), weather=None
    )
    assert set(state.rooms) == {"r1"}


def test_no_windows_leave_window_parts_empty():
    result, state = run(
        house([room("r1", ["sensor.a"], S)], [region("g_s", S, ["sensor.o"])]),
        {("sensor.a", T): 21.0, ("sensor.o", T): 15.0},
        EngineState.empty(),
        at(),
        weather=None,
    )
    r1 = result.rooms["r1"]
    assert (r1.windows, r1.cooling_down, r1.heating_up) == (None, None, None)
    assert r1.open_while_conditioning is None
    assert result.windows == {}
    assert state.windows == {}
    house_result = result.house
    assert house_result.any_cooling_down is None
    assert house_result.any_heating_up is None
    assert house_result.any_open_while_conditioning is None
    assert (house_result.any_cover_to_close, house_result.covers_to_close) == (
        False,
        (),
    )


# Contract (logic §14)


def test_weather_offsets_are_learned_before_directions_resolve():
    # N has a temperature but no humidity: the weather pair of N uses the
    # temperature offset learned in this very evaluation (11.0 + 2.0 = 13.0).
    model = house(
        [room("r1", ["sensor.room"], N)],
        [region("g_n", N, ["sensor.n_t"], ["sensor.n_h"])],
    )
    values = {
        ("sensor.room", T): 21.0,
        ("sensor.n_t", T): 13.0,
        ("sensor.n_h", H): Status.UNAVAILABLE,
    }
    result, state = run(model, values, EngineState.empty(), at())
    assert (N, T) in state.hub.weather_offsets.offsets
    ah = result.rooms["r1"].outdoor.absolute_humidity
    assert ah.stage is Stage.WEATHER
    assert ah.value == pytest.approx(absolute_humidity(13.0, 80.0))


@pytest.mark.parametrize(
    ("failing", "fed"), [((), True), ((N, W, S), False)], ids=["own", "weather"]
)
def test_forecast_bias_is_fed_only_off_the_weather_stage(failing, fed):
    model = house([room("r1", ["sensor.room"], N)], three_regions())
    values = {("sensor.room", T): 21.0, **outside(failing)}
    result, state = run(model, values, EngineState.empty(), at())
    assert (result.house.outdoor.stage is Stage.WEATHER) is not fed
    _, state = run(model, values, state, at(1))
    bias = state.hub.forecast_bias
    assert (bias.obs_max is not None) is fed
    if fed:
        assert bias.obs_max == pytest.approx(13.33, abs=0.01)


@pytest.mark.parametrize(
    ("temperature", "humidity", "status"),
    [
        (Status.UNAVAILABLE, Status.UNKNOWN, Status.UNAVAILABLE),  # first metric
        (Status.UNKNOWN, Status.UNAVAILABLE, Status.UNKNOWN),
        (Status.UNAVAILABLE, 50.0, None),  # humidity still works: not an outage
    ],
)
def test_outages_use_all_readings_of_an_entity(temperature, humidity, status):
    model = house(
        [room("r1", ["climate.x", "sensor.y"], humidity=["climate.x"])], weather=None
    )
    values = {
        ("climate.x", T): temperature,
        ("climate.x", H): humidity,
        ("sensor.y", T): 21.0,
    }
    state = EngineState.empty()
    _, state = run(model, values, state, at(0), weather=None)
    result, state = run(model, values, state, at(6 * 60), weather=None)
    found = {o.entity_id: o.status for o in result.house.outages}
    assert found == ({} if status is None else {"r1/climate.x": status})


def test_outage_waits_for_the_repair_delay_and_reports_stale_sources():
    model = house([], [region("g_n", N, ["sensor.a", "sensor.b"])], weather=None)

    def values(now):
        return {
            ("sensor.a", T): Reading(
                "sensor.a", 20.0, Status.OK, now - timedelta(days=1)
            ),
            ("sensor.b", T): 18.0,
        }

    state = EngineState.empty()
    for minutes, count in [(0, 0), (6 * 60 - 1, 0), (6 * 60, 1)]:
        result, state = run(
            model, values(at(minutes)), state, at(minutes), weather=None
        )
        assert len(result.house.outages) == count
    outage = result.house.outages[0]
    assert (outage.entity_id, outage.status) == ("g_n/sensor.a", Status.STALE)
    assert outage.invalid_since == at(0)
    assert state.hub.outages.invalid_since == {"g_n/sensor.a": at(0)}

    # a source that works again leaves the state
    result, state = run(
        model,
        {("sensor.a", T): 20.0, ("sensor.b", T): 18.0},
        state,
        at(6 * 60 + 1),
        weather=None,
    )
    assert result.house.outages == ()
    assert state.hub.outages.invalid_since == {}


# Isolation (N2)


@pytest.fixture
def break_bad_sensors(monkeypatch):
    real = engine.resolve

    def resolve(readings, *args):
        if any(r.entity_id.startswith("sensor.bad") for r in readings):
            raise RuntimeError("boom")
        return real(readings, *args)

    monkeypatch.setattr(engine, "resolve", resolve)


def _isolation_model():
    return house(
        [room("r_ok", ["sensor.ok"], S), room("r_bad", ["sensor.bad_room"], S)],
        [
            region("g_s", S, ["sensor.bad_out"]),
            region("g_n", N, ["sensor.n_out"]),
        ],
    )


ISOLATION_VALUES = {
    ("sensor.ok", T): 21.0,
    ("sensor.bad_room", T): 22.0,
    ("sensor.bad_out", T): 14.0,
    ("sensor.n_out", T): 12.0,
}


@pytest.fixture
def previous():
    """A clean first evaluation of the isolation model."""
    return run(_isolation_model(), ISOLATION_VALUES, EngineState.empty(), at())


def test_failing_room_and_region_leave_the_rest_intact(previous, break_bad_sensors):
    _, state = previous
    result, new_state = run(_isolation_model(), ISOLATION_VALUES, state, at(2))
    assert set(result.failures) == {"r_bad", "g_s"}
    assert all("boom" in text for text in result.failures.values())

    # failed objects have no result and keep their previous state
    assert "r_bad" not in result.rooms
    assert "g_s" not in result.regions
    assert new_state.rooms["r_bad"] is state.rooms["r_bad"]
    assert new_state.regions["g_s"] is state.regions["g_s"]

    # the others are evaluated: the healthy room sees the failed region as missing data
    assert new_state.rooms["r_ok"] != state.rooms["r_ok"]
    outdoor = result.rooms["r_ok"].outdoor.temperature
    assert (outdoor.value, outdoor.stage, outdoor.regions) == (
        12.0,
        Stage.OPPOSITE,
        (N,),
    )
    assert result.regions["g_n"].values.temperature.stage is Stage.PRIMARY
    assert result.house is not None
    assert result.house.indoor.value == 21.0
    assert result.house.outdoor.per_region == {N: 12.0}


def test_failing_hub_part_keeps_its_state(monkeypatch):
    model = house([room("r1", ["sensor.a"], S)], [region("g_s", S, ["sensor.o"])])
    forecast = Forecast(
        tuple(ForecastPoint(at(60 * i), 18.0 + i / 2) for i in range(24)), hourly=True
    )
    values = {("sensor.a", T): 21.0, ("sensor.o", T): 15.0}
    _, state = run(
        model, values, EngineState.empty(), at(), weather=None, forecast=forecast
    )
    assert state.hub.strategy is Strategy.PREVENT_HEAT_UP

    def boom(*args):
        raise ValueError("no strategy")

    monkeypatch.setattr(engine, "daily_strategy", boom)
    result, new_state = run(
        model, values, state, at(1), weather=None, forecast=forecast
    )
    assert result.failures == {"hub/strategy": "ValueError: no strategy"}
    assert new_state.hub.strategy is Strategy.PREVENT_HEAT_UP
    assert result.house.strategy.strategy is None
    assert result.rooms["r1"].temperature.value == 21.0
    assert "g_s" in result.regions


# Windows (docs/logic.md §8)


def cold_forecast() -> Forecast:
    """A cold day: prevent cool-down for comfort 20 to 24."""
    return Forecast(
        tuple(ForecastPoint(at(60 * i), 2.0 + i / 4) for i in range(24)), hourly=True
    )


def window_result(model, contacts):
    """First evaluation of a house; returns the result of window `w`."""
    result, _ = run(
        model, {}, EngineState.empty(), at(), weather=None, contacts=contacts
    )
    return result.windows["w"]


@pytest.mark.parametrize(
    ("states", "level", "leaves"),
    [
        pytest.param(("on", "off", "off"), Level.TILTED, OpenLeaves.LEFT, id="tilted"),
        pytest.param(("on", "on", "on"), Level.OPEN, OpenLeaves.BOTH, id="open"),
        pytest.param(("off", "off", "off"), Level.CLOSED, OpenLeaves.NONE, id="closed"),
        pytest.param(
            ("off", "off", "on"), Level.OPEN, OpenLeaves.UNKNOWN, id="implausible"
        ),
    ],
)
def test_scenario_5_double_leaf_with_tilt_discriminator(states, level, leaves):
    model = house(
        windows=[
            window(
                "w",
                None,
                type="double",
                leaf_left="binary_sensor.l",
                leaf_right="binary_sensor.r",
                tilt="binary_sensor.t",
            )
        ]
    )
    names = ("binary_sensor.l", "binary_sensor.r", "binary_sensor.t")
    found = window_result(model, dict(zip(names, states, strict=True)))
    assert (found.level.level, found.level.open_leaves) == (level, leaves)
    assert found.state.level is level


@pytest.mark.parametrize(
    ("handle", "level"),
    [("on", Level.AJAR), ("off", Level.CLOSED)],
)
def test_scenario_6_turned_handle_is_ajar_and_does_not_ventilate(handle, level):
    model = house(
        [room("r1", ["sensor.a"])],
        windows=[window("w", "r1", handle="binary_sensor.handle")],
    )
    result, _ = run(
        model,
        {("sensor.a", T): 21.0},
        EngineState.empty(),
        at(),
        weather=None,
        contacts={"binary_sensor.w": "off", "binary_sensor.handle": handle},
    )
    assert result.windows["w"].state.level is level
    assert result.windows["w"].state.ventilating is False
    assert result.rooms["r1"].windows.ventilating is False


@pytest.mark.parametrize(
    ("door", "conservatory", "ventilating"),
    [
        ("on", "on", True),
        ("on", "off", False),
        ("off", "on", False),
        ("unavailable", "off", False),  # no air path through a closed opening
        ("unavailable", "on", None),
    ],
)
def test_scenario_7_pass_through_needs_both_openings(door, conservatory, ventilating):
    model = house(
        windows=[
            window(
                "w",
                None,
                type="pass_through",
                inner="binary_sensor.door",
                outer="binary_sensor.conservatory",
            )
        ]
    )
    found = window_result(
        model,
        {"binary_sensor.door": door, "binary_sensor.conservatory": conservatory},
    )
    assert found.state.ventilating is ventilating


def test_scenario_9_humid_bathroom_bursts_then_closes():
    model = house(
        [room("bath", ["sensor.t"], S, ["sensor.h"])],
        [region("g_s", S, ["sensor.o_t"], ["sensor.o_h"])],
        weather=None,
        windows=[window("w1", "bath")],
    )
    values = {
        ("sensor.t", T): 22.0,
        ("sensor.h", H): 68.0,
        ("sensor.o_t", T): 5.0,
        ("sensor.o_h", H): 60.0,
    }
    # (minutes, contact, recommendation, reason, cooling down); the window opens at 1
    timeline = [
        (0, "off", Recommendation.OPEN, Reason.BURST_DRY, False),
        (1, "on", Recommendation.OPEN, Reason.BURST_DRY, False),  # debounce pending
        (1.2, "on", Recommendation.KEEP_OPEN, Reason.BURST_DRY, False),
        (10.9, "on", Recommendation.KEEP_OPEN, Reason.BURST_DRY, False),
        (11.2, "on", Recommendation.CLOSE, Reason.BURST_DONE, True),
        (30, "off", Recommendation.CLOSE, Reason.BURST_DONE, True),  # debounce pending
        (31, "off", Recommendation.KEEP_CLOSED, Reason.BURST_DONE, False),
    ]
    state = EngineState.empty()
    for minutes, contact, recommendation, reason, cooling_down in timeline:
        result, state = run(
            model,
            values,
            state,
            at(minutes),
            weather=None,
            forecast=cold_forecast(),
            contacts={"binary_sensor.w1": contact},
        )
        assert not result.failures
        assert result.house.strategy.strategy is Strategy.PREVENT_COOL_DOWN
        found = result.rooms["bath"]
        assert (found.recommendation.recommendation, found.recommendation.reason) == (
            recommendation,
            reason,
        ), minutes
        assert found.cooling_down is cooling_down, minutes
    assert result.rooms["bath"].windows.open_since is None


def test_scenario_10_creation_order_does_not_matter():
    rooms = [
        room("bath", ["sensor.t"], S, ["sensor.h"]),
        room("hall", ["sensor.hall"], S, devices=["climate.heater"]),
    ]
    regions = [region("g_s", S, ["sensor.o_t"], ["sensor.o_h"])]
    windows = [
        window("w1", "bath", cover="cover.w1"),
        window("w2", "hall", facing_degrees=180.0),
        window("w3", None),
    ]
    forward = house(rooms, regions, weather=None, windows=windows)
    backward = house(rooms[::-1], regions[::-1], weather=None, windows=windows[::-1])
    values = {
        ("sensor.t", T): 22.0,
        ("sensor.h", H): 68.0,
        ("sensor.hall", T): 25.0,
        ("sensor.o_t", T): 5.0,
        ("sensor.o_h", H): 60.0,
    }
    states = [EngineState.empty(), EngineState.empty()]
    for minutes, contact in [
        (0, "off"),
        (1, "on"),
        (1.2, "on"),
        (12, "on"),
        (13, "off"),
    ]:
        results = []
        for index, model in enumerate((forward, backward)):
            result, states[index] = run(
                model,
                values,
                states[index],
                at(minutes),
                weather=None,
                forecast=cold_forecast(),
                contacts={f"binary_sensor.w{n}": contact for n in (1, 2, 3)},
                climate={"climate.heater": ClimateDevice("heating", "heat")},
                covers={"cover.w1": CoverPosition.NOT_CLOSED},
                sun=(180.0, 40.0),
            )
            results.append(result)
        assert results[0] == results[1]
        assert states[0] == states[1]
    assert results[0].windows["w3"].cover.reason is CoverReason.NO_ROOM


def test_debounce_publishes_after_five_seconds_and_a_bounce_keeps_open_since():
    model = house(windows=[window("w", None)])
    state = EngineState.empty()
    published, since = [], []
    # seconds, contact: opens at 10, bounces closed at 20 for 3 s, closes for good at 30
    steps = [
        (0, "off"),
        (10, "on"),
        (12, "on"),
        (15, "on"),
        (20, "off"),
        (23, "on"),
        (28, "on"),
        (30, "off"),
        (34, "off"),
        (35, "off"),
    ]
    for seconds, contact in steps:
        result, state = run(
            model,
            {},
            state,
            at(seconds / 60),
            weather=None,
            contacts={"binary_sensor.w": contact},
        )
        published.append(result.windows["w"].state.level)
        since.append(result.windows["w"].state.open_since)
    closed, opened = Level.CLOSED, Level.OPEN
    assert published == [closed] * 3 + [opened] * 6 + [closed]
    assert since == [None] * 3 + [at(10 / 60)] * 6 + [None]


def test_open_since_starts_from_the_latest_contact_change_after_a_restart():
    model = house(
        windows=[
            window(
                "w",
                None,
                type="double",
                leaf_left="binary_sensor.l",
                leaf_right="binary_sensor.r",
            )
        ]
    )
    contacts = {
        "binary_sensor.l": Contact("on", at(-60)),
        "binary_sensor.r": Contact("on", at(-20)),
    }
    assert window_result(model, contacts).state.open_since == at(-20)
    # without a hint the evaluation time is the best guess
    found = window_result(model, {"binary_sensor.l": "on", "binary_sensor.r": "on"})
    assert found.state.open_since == at()


def test_restart_hint_ignores_contacts_that_report_closed():
    model = house(
        windows=[
            window(
                "w",
                None,
                type="double",
                leaf_left="binary_sensor.l",
                leaf_right="binary_sensor.r",
            )
        ]
    )
    contacts = {
        "binary_sensor.l": Contact("on", at(-60)),
        "binary_sensor.r": Contact("off", at(-30)),
    }
    assert window_result(model, contacts).state.open_since == at(-60)


def test_the_windows_min_level_reaches_debounce_and_open_since():
    model = house(
        windows=[window("w", None, handle="binary_sensor.handle", min_level="ajar")]
    )
    found = window_result(
        model, {"binary_sensor.w": "off", "binary_sensor.handle": "on"}
    )
    assert found.state.level is Level.AJAR
    assert found.state.ventilating is True
    assert found.state.open_since == at()


def test_a_missing_contact_is_a_missing_value():
    found = window_result(house(windows=[window("w", None)]), {})
    assert found.level.level is None
    assert found.state.ventilating is None


def test_window_without_room_has_a_state_and_a_no_room_cover():
    model = house([room("r1", ["sensor.a"], S)], windows=[window("w", None)])
    result, state = run(
        model,
        {("sensor.a", T): 21.0},
        EngineState.empty(),
        at(),
        weather=None,
        contacts={"binary_sensor.w": "on"},
        sun=(180.0, 40.0),
    )
    found = result.windows["w"]
    assert found.state.ventilating is True
    assert (found.cover.advice, found.cover.reason) == (
        CoverAdvice.NONE,
        CoverReason.NO_ROOM,
    )
    assert result.rooms["r1"].windows is None
    assert state.windows["w"].cover.reason is CoverReason.NO_ROOM
    assert not result.failures


def test_window_of_a_failed_room_reports_missing_data_not_a_missing_room(monkeypatch):
    real = engine.resolve

    def resolve(readings, *args):
        if any(r.entity_id == "sensor.bad" for r in readings):
            raise RuntimeError("boom")
        return real(readings, *args)

    monkeypatch.setattr(engine, "resolve", resolve)
    model = house(
        [room("bad", ["sensor.bad"], S), room("ok", ["sensor.ok"], S)],
        windows=[window("w_bad", "bad"), window("w_ok", "ok")],
    )
    result, _ = run(
        model,
        {("sensor.bad", T): 22.0, ("sensor.ok", T): 21.0},
        EngineState.empty(),
        at(),
        weather=None,
        contacts={"binary_sensor.w_bad": "on", "binary_sensor.w_ok": "on"},
        sun=(180.0, 40.0),
    )
    assert set(result.failures) == {"bad"}
    assert "bad" not in result.rooms
    bad = result.windows["w_bad"]
    assert bad.state.ventilating is True
    assert (bad.cover.advice, bad.cover.reason) == (
        CoverAdvice.NONE,
        CoverReason.NO_DATA,
    )
    assert result.windows["w_ok"].cover.reason is CoverReason.NO_HEAT_RISK


def test_failed_window_counts_as_unknown_and_keeps_its_store(monkeypatch):
    model = house(
        [room("r1", ["sensor.a"], S)],
        [region("g_s", S, ["sensor.o"])],
        windows=[window("w", "r1")],
    )
    values = {("sensor.a", T): 21.0, ("sensor.o", T): 15.0}
    contacts = {"binary_sensor.w": "off"}
    _, state = run(
        model, values, EngineState.empty(), at(), weather=None, contacts=contacts
    )

    def boom(*args):
        raise ValueError("bad contact")

    monkeypatch.setattr(engine, "window_level", boom)
    result, new_state = run(
        model, values, state, at(1), weather=None, contacts=contacts
    )
    assert result.failures == {"w": "ValueError: bad contact"}
    assert "w" not in result.windows
    assert new_state.windows["w"] is state.windows["w"]
    aggregated = result.rooms["r1"].windows
    assert (aggregated.level, aggregated.ventilating) == (None, None)


# Warnings, A12 and the any-flags


@pytest.mark.parametrize(
    ("forecast", "cooling_down"),
    [(cold_forecast(), True), (None, False)],
    ids=["cool_down_day", "neutral_day"],
)
def test_warning_cooling_down_after_the_burst_time(forecast, cooling_down):
    model = house(
        [room("r1", ["sensor.a"], S)],
        [region("g_s", S, ["sensor.o"])],
        weather=None,
        windows=[window("w", "r1")],
    )
    values = {("sensor.a", T): 21.0, ("sensor.o", T): 5.0}
    contacts = {"binary_sensor.w": Contact("on", at(0))}
    state = EngineState.empty()
    flags = []
    for minutes in (1, 9.9, 10):
        result, state = run(
            model,
            values,
            state,
            at(minutes),
            weather=None,
            forecast=forecast,
            contacts=contacts,
        )
        flags.append(result.rooms["r1"].cooling_down)
        assert result.rooms["r1"].recommendation.wanted_open is False
    assert flags == [False, False, cooling_down]
    assert result.rooms["r1"].heating_up is False
    assert result.rooms["r1"].open_while_conditioning is None  # no devices


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        (ClimateDevice("heating", "heat"), True),
        (ClimateDevice("idle", "heat"), False),
        (ClimateDevice(None, "off"), False),
        (None, False),  # not in the snapshot
    ],
)
def test_a12_open_window_while_a_device_is_active(device, expected):
    model = house(
        [room("r1", ["sensor.a"], S, devices=["climate.heater"])],
        windows=[window("w", "r1")],
    )
    result, _ = run(
        model,
        {("sensor.a", T): 21.0},
        EngineState.empty(),
        at(15),
        weather=None,
        contacts={"binary_sensor.w": Contact("on", at(0))},
        climate={"climate.heater": device} if device else {},
    )
    assert result.rooms["r1"].open_while_conditioning is expected
    assert result.house.any_open_while_conditioning is expected


@pytest.mark.parametrize(
    ("contact", "device", "expected"),
    [
        pytest.param("on", "heating", (True, False, True), id="open_and_heating"),
        pytest.param("on", "idle", (True, False, False), id="open_and_idle"),
        pytest.param("off", "heating", (False, False, False), id="closed"),
    ],
)
def test_house_any_flags_cover_rooms_with_windows_only(contact, device, expected):
    model = house(
        [
            room("a", ["sensor.a"], S, devices=["climate.heater"]),
            room("b", ["sensor.b"], S),
            room("c", ["sensor.c"], S),  # no windows: not part of any flag
        ],
        [region("g_s", S, ["sensor.o"])],
        weather=None,
        windows=[window("wa", "a"), window("wb", "b")],
    )
    result, _ = run(
        model,
        {
            ("sensor.a", T): 21.0,
            ("sensor.b", T): 21.0,
            ("sensor.c", T): 21.0,
            ("sensor.o", T): 5.0,
        },
        EngineState.empty(),
        at(15),
        weather=None,
        forecast=cold_forecast(),
        contacts={
            "binary_sensor.wa": Contact(contact, at(0)),
            "binary_sensor.wb": Contact(contact, at(0)),
        },
        climate={"climate.heater": ClimateDevice(device, "heat")},
    )
    flags = result.house
    assert (
        flags.any_cooling_down,
        flags.any_heating_up,
        flags.any_open_while_conditioning,
    ) == expected
    assert result.rooms["c"].cooling_down is None


# Covers (docs/logic.md §10)


@pytest.mark.parametrize(
    ("cover", "advice"),
    [(None, CoverAdvice.CLOSE), (CoverPosition.CLOSED, CoverAdvice.KEEP_CLOSED)],
)
def test_cover_closes_against_sun_heat_and_feeds_the_house_flag(cover, advice):
    model = house(
        [room("r1", ["sensor.a"], S)],
        windows=[window("w", "r1", cover="cover.w")],
    )
    result, state = run(
        model,
        {("sensor.a", T): 25.0},
        EngineState.empty(),
        at(),
        weather=None,
        contacts={"binary_sensor.w": "off"},
        covers={"cover.w": cover} if cover else {},
        sun=(180.0, 40.0),
    )
    found = result.windows["w"].cover
    assert (found.advice, found.reason) == (advice, CoverReason.SUN_HEAT)
    assert state.windows["w"].cover is not None
    assert result.house.any_cover_to_close is True
    assert result.house.covers_to_close == (("w", CoverReason.SUN_HEAT),)


def test_exact_degrees_win_without_a_direction():
    model = house(
        [room("r1", ["sensor.a"])],  # no side
        windows=[window("w", "r1", facing_degrees=180.0)],
    )
    result, _ = run(
        model,
        {("sensor.a", T): 25.0},
        EngineState.empty(),
        at(),
        weather=None,
        sun=(180.0, 40.0),
    )
    assert result.windows["w"].cover.reason is CoverReason.SUN_HEAT


def test_no_direction_and_no_degrees_means_no_data_and_keeps_the_cover_state():
    model = house([room("r1", ["sensor.a"])], windows=[window("w", "r1")])
    result, state = run(
        model,
        {("sensor.a", T): 25.0},
        EngineState.empty(),
        at(),
        weather=None,
        sun=(180.0, 40.0),
    )
    found = result.windows["w"].cover
    assert (found.advice, found.reason) == (CoverAdvice.NONE, CoverReason.NO_DATA)
    assert state.windows["w"].cover is None
    assert result.house.any_cover_to_close is False


# Outages of failed objects


def test_outage_timer_survives_a_failed_evaluation_of_its_room(monkeypatch):
    broken = {"on": False}
    real = engine.resolve

    def resolve(readings, *args):
        if broken["on"]:
            raise RuntimeError("boom")
        return real(readings, *args)

    monkeypatch.setattr(engine, "resolve", resolve)
    model = house([room("r1", ["sensor.a"])], weather=None)
    values = {("sensor.a", T): Status.UNAVAILABLE}
    _, state = run(model, values, EngineState.empty(), at(0), weather=None)
    assert state.hub.outages.invalid_since == {"r1/sensor.a": at(0)}

    broken["on"] = True
    result, state = run(model, values, state, at(60), weather=None)
    assert set(result.failures) == {"r1"}
    assert state.hub.outages.invalid_since == {"r1/sensor.a": at(0)}

    broken["on"] = False
    result, state = run(model, values, state, at(6 * 60), weather=None)
    assert not result.failures
    (outage,) = result.house.outages
    assert (outage.entity_id, outage.invalid_since) == ("r1/sensor.a", at(0))
