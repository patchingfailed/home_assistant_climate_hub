"""Engine part 1 (docs/integration.md §4): scenarios 2, 3, 4, 11, 12, the logic §14
contract and isolation. Hand-built models and snapshots, no Home Assistant."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from custom_components.climate_hub.logic import engine
from custom_components.climate_hub.logic.engine import (
    Comfort,
    EngineState,
    Forecast,
    Snapshot,
    evaluate,
)
from custom_components.climate_hub.logic.model import (
    RegionModel,
    RoomModel,
    build_house,
    parse_region,
    parse_room,
    parse_settings,
)
from custom_components.climate_hub.logic.outdoor import (
    Direction,
    OutdoorReason,
    WeatherReadings,
)
from custom_components.climate_hub.logic.psychro import absolute_humidity
from custom_components.climate_hub.logic.recommendation import Reason, Recommendation
from custom_components.climate_hub.logic.sources import (
    Metric,
    Reading,
    Stage,
    Status,
)
from custom_components.climate_hub.logic.strategy import ForecastPoint, Strategy

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
) -> RoomModel:
    data = {
        "area": f"area_{room_id}",
        "side": side or "none",
        "temperature": temperature,
        "humidity": humidity or [],
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


def house(rooms=(), regions=(), weather: str | None = "weather.home"):
    return build_house(
        SETTINGS,
        weather,
        {r.id: r for r in rooms},
        {r.id: r for r in regions},
        {},
    )


def weather_readings(now, t=11.0, h=80.0, p=1021.0) -> WeatherReadings:
    return WeatherReadings(
        *(Reading("weather.home", v, Status.OK, now) for v in (t, h, p))
    )


def snapshot(now, values, *, weather=True, forecast=None) -> Snapshot:
    """`values` maps (entity, metric) to a float, a Status or a ready Reading."""
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
        contacts={},
        climate={},
        covers={},
        weather=weather_readings(now) if weather is True else weather or None,
        clouds=None,
        forecast=forecast,
        sun_azimuth=None,
        sun_elevation=None,
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
    assert r1.recommendation.reason is Reason.NO_DATA
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
