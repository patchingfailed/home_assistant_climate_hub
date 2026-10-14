"""Codec of the persisted engine state (docs/integration.md §7)."""

import json
from datetime import UTC, date, datetime, timedelta, timezone

from custom_components.climate_hub.logic.codec import (
    dump_comfort,
    dump_state,
    load_comfort,
    load_state,
)
from custom_components.climate_hub.logic.comfort import (
    Dryness,
    Position,
    Relation,
    Trend,
    TrendState,
)
from custom_components.climate_hub.logic.cover import (
    CoverReason,
    CoverState,
    CoverWanted,
)
from custom_components.climate_hub.logic.engine import (
    Comfort,
    EngineState,
    HubState,
    RegionState,
    RoomState,
    WindowStore,
)
from custom_components.climate_hub.logic.house import OutageState
from custom_components.climate_hub.logic.model import (
    HouseModel,
    RoomModel,
    Settings,
    build_house,
    parse_region,
    parse_window,
)
from custom_components.climate_hub.logic.outdoor import Direction, WeatherOffsets
from custom_components.climate_hub.logic.recommendation import Goal, GoalState
from custom_components.climate_hub.logic.sources import Metric, Offset, SourceState
from custom_components.climate_hub.logic.strategy import ForecastBias, Strategy
from custom_components.climate_hub.logic.window import Debounced, Level

T, H, P = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE
NOW = datetime(2026, 10, 14, 12, 30, 15, 250000, tzinfo=UTC)
CEST = timezone(timedelta(hours=2))
SETTINGS = Settings(
    timedelta(minutes=40), timedelta(minutes=10), 60.0, timedelta(hours=6)
)


def _model(rooms=("r1", "r2"), regions=("g1",), windows=("w1",)) -> HouseModel:
    room_models = {
        rid: RoomModel(
            rid,
            f"a_{rid}",
            None,
            {T: ("sensor.t",), H: (), P: ()},
            (),
            SETTINGS.max_age,
            (),
        )
        for rid in rooms
    }
    region_models = {
        rid: parse_region(
            rid,
            {"area": "street", "direction": "n", "temperature": ["sensor.o"]},
            SETTINGS,
            {},
        )
        for rid in regions
    }
    window_models = {
        wid: parse_window(
            wid,
            {
                "area": "nowhere",
                "type": "single",
                "name": "Window",
                "leaf": "binary_sensor.leaf",
            },
        )
        for wid in windows
    }
    return build_house(SETTINGS, None, room_models, region_models, window_models)


def _offset(learned: float, minutes: int = 30) -> Offset:
    return Offset(
        learned=learned,
        paired=timedelta(minutes=minutes, seconds=0.5),
        last_sample_at=NOW - timedelta(minutes=1),
        last_deviation=learned + 0.25,
    )


def _source() -> SourceState:
    return SourceState(
        offsets={"sensor.a": _offset(0.5), "sensor.b": _offset(-1.25, 90)},
        rank1="sensor.a",
        winner="sensor.b",
        switched_at=NOW - timedelta(minutes=7),
        anchor=-0.75,
    )


def _room() -> RoomState:
    return RoomState(
        sources={T: _source(), H: SourceState({}, None, None, None, None)},
        trend_state=TrendState(
            (
                (NOW - timedelta(minutes=20), 21.5),
                (NOW - timedelta(minutes=10, seconds=3), 21.75),
                (NOW.astimezone(CEST), 22.0),
            )
        ),
        position=Position.WITHIN,
        relation=Relation.WARMER,
        dryness=Dryness.MORE_HUMID,
        trend=Trend.RISING,
        goal=GoalState(
            goal=Goal.BURST,
            started_at=NOW - timedelta(minutes=3),
            pause_until=NOW + timedelta(hours=1),
            humid_guard=True,
        ),
    )


def _window() -> WindowStore:
    return WindowStore(
        debounced=Debounced(
            raw=Level.TILTED,
            raw_since=NOW - timedelta(seconds=4),
            published=Level.CLOSED,
            ventilating_since=NOW - timedelta(minutes=2),
        ),
        open_since=NOW - timedelta(minutes=2),
        cover=CoverState(
            wanted=CoverWanted.CLOSED,
            reason=CoverReason.SUN_HEAT,
            since=NOW - timedelta(minutes=9),
            relation=Relation.COLDER,
            heat_risk=True,
        ),
    )


def _hub() -> HubState:
    return HubState(
        weather_offsets=WeatherOffsets(
            {
                (Direction.N, T): _offset(1.5),
                (Direction.S, H): _offset(-4.0, 200),
                (Direction.W, P): _offset(0.125),
            }
        ),
        forecast_bias=ForecastBias(
            bias_max=1.5,
            bias_min=-0.5,
            samples=12,
            day=date(2026, 10, 14),
            day_f_max=18.0,
            day_f_min=9.5,
            obs_max=17.25,
            obs_min=None,
            covered=timedelta(hours=7, seconds=30),
            last_at=NOW,
        ),
        strategy=Strategy.PREVENT_HEAT_UP,
        outages=OutageState(
            {"sensor.a": NOW - timedelta(hours=2), "sensor.b": NOW.astimezone(CEST)}
        ),
    )


def _state() -> EngineState:
    return EngineState(
        rooms={
            "r1": _room(),
            "r2": RoomState({}, TrendState(), None, None, None, None, None),
        },
        regions={"g1": RegionState({T: _source(), P: _source()})},
        windows={"w1": _window()},
        hub=_hub(),
    )


def _through_json(data):
    return json.loads(json.dumps(data))


def test_round_trip_every_type():
    state = _state()
    data = _through_json(dump_state(state))
    assert load_state(data, _model()) == state


def test_formats():
    data = dump_state(_state())
    assert data["rooms"]["r1"]["sources"]["temperature"]["offsets"]["sensor.a"] == {
        "learned": 0.5,
        "paired": 1800.5,
        "last_sample_at": "2026-10-14T12:29:15.250000+00:00",
        "last_deviation": 0.75,
    }
    assert (
        data["rooms"]["r1"]["trend_state"][2][0] == "2026-10-14T14:30:15.250000+02:00"
    )
    assert data["rooms"]["r1"]["goal"]["goal"] == "burst"
    assert data["windows"]["w1"]["debounced"]["raw"] == "tilted"
    assert set(data["hub"]["weather_offsets"]) == {
        "n/temperature",
        "s/humidity",
        "w/pressure",
    }
    assert data["hub"]["forecast_bias"]["day"] == "2026-10-14"
    assert data["hub"]["strategy"] == "prevent_heat_up"


def test_empty_state_round_trip():
    empty = EngineState.empty()
    assert load_state(_through_json(dump_state(empty)), _model()) == empty


def test_empty_input():
    assert load_state(None, _model()) == EngineState.empty()
    assert load_state({}, _model()) == EngineState.empty()


def test_unknown_ids_are_pruned():
    data = _through_json(dump_state(_state()))
    loaded = load_state(data, _model(rooms=("r2",), regions=(), windows=()))
    assert set(loaded.rooms) == {"r2"}
    assert loaded.regions == {}
    assert loaded.windows == {}
    assert loaded.hub == _hub()


def test_corrupt_room_falls_back_while_others_load():
    data = _through_json(dump_state(_state()))
    data["rooms"]["r1"]["goal"]["goal"] = "not-a-goal"
    data["regions"]["g1"] = "garbage"
    loaded = load_state(data, _model())
    assert "r1" not in loaded.rooms
    assert loaded.rooms["r2"] == _state().rooms["r2"]
    assert loaded.regions == {}
    assert loaded.windows["w1"] == _window()


def test_naive_datetime_is_corrupt():
    data = _through_json(dump_state(_state()))
    data["windows"]["w1"]["open_since"] = "2026-10-14T12:00:00"
    assert load_state(data, _model()).windows == {}


def test_corrupt_hub_starts_fresh():
    data = _through_json(dump_state(_state()))
    data["hub"]["weather_offsets"]["x/temperature"] = {}
    loaded = load_state(data, _model())
    assert loaded.hub == EngineState.empty().hub
    assert loaded.rooms["r1"] == _room()


def test_unknown_fields_are_ignored():
    data = _through_json(dump_state(_state()))
    data["future"] = 1
    data["rooms"]["r1"]["extra"] = {"a": 1}
    data["hub"]["extra"] = []
    assert load_state(data, _model()) == _state()


def test_comfort_round_trip():
    comfort = Comfort(19.5, 25.0, 3.0)
    assert load_comfort(_through_json(dump_comfort(comfort))) == comfort


def test_comfort_defaults():
    default = Comfort(20.0, 24.0, 2.0)
    assert load_comfort(None) == default
    assert load_comfort({}) == default
    assert load_comfort({"min": "x", "max": None, "threshold": True}) == default
    assert load_comfort({"min": 25.0, "max": 24.0, "threshold": 1.0}) == Comfort(
        20.0, 24.0, 1.0
    )
    assert load_comfort({"min": 18, "threshold": 4}) == Comfort(18.0, 24.0, 4.0)
