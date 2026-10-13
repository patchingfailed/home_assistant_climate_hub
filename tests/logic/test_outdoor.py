"""Table cases of docs/logic.md §5."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.climate_hub.logic.outdoor import (
    Direction,
    OutdoorReason,
    RegionOwn,
    WeatherOffsets,
    WeatherReadings,
    fallback_chain,
    house_outdoor,
    learn_weather_offsets,
    resolve_direction,
)
from custom_components.climate_hub.logic.sources import (
    Metric,
    Offset,
    Reading,
    Resolution,
    Stage,
    Status,
)

N, E, S, W = Direction.N, Direction.E, Direction.S, Direction.W
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
TEMPERATURE, HUMIDITY, PRESSURE = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE

OWN = {N: (13.0, 71.0), S: (12.5, 76.0), W: (14.5, 65.0)}
STATION_PRESSURE = 1003.0
NO_OFFSETS = WeatherOffsets({})


def resolution(value: float | None, stage: Stage = Stage.PRIMARY) -> Resolution:
    if value is None:
        return Resolution(None, None, None, Stage.NONE, None, Status.MISSING, ())
    return Resolution(value, "sensor.x", 1, stage, None, None, ())


def regions(
    failing: frozenset[tuple[Direction, Metric]] = frozenset(),
    fallback: frozenset[tuple[Direction, Metric]] = frozenset(),
) -> dict[Direction, RegionOwn]:
    def make(d: Direction, metric: Metric, value: float) -> Resolution:
        if (d, metric) in failing:
            return resolution(None)
        return resolution(
            value, Stage.FALLBACK if (d, metric) in fallback else Stage.PRIMARY
        )

    return {
        d: RegionOwn(
            d,
            make(d, TEMPERATURE, t),
            make(d, HUMIDITY, h),
            make(d, PRESSURE, STATION_PRESSURE),
        )
        for d, (t, h) in OWN.items()
    }


def weather(*, stale: bool = False) -> WeatherReadings:
    reported = NOW - timedelta(hours=3) if stale else NOW - timedelta(minutes=5)

    def reading(value: float) -> Reading:
        return Reading("weather.home", value, Status.OK, reported)

    return WeatherReadings(reading(11.0), reading(80.0), reading(1021.0))


def fail(*pairs: tuple[Direction, Metric]) -> frozenset[tuple[Direction, Metric]]:
    return frozenset(pairs)


def all_fail(*directions: Direction) -> frozenset[tuple[Direction, Metric]]:
    return frozenset((d, m) for d in directions for m in Metric)


@pytest.mark.parametrize(
    ("configured", "direction", "chain"),
    [
        (
            {N, W, S},
            N,
            [(Stage.PRIMARY, (N,)), (Stage.NEIGHBOUR, (W,)), (Stage.OPPOSITE, (S,))],
        ),
        ({N, W, S}, E, [(Stage.NEIGHBOUR, (N, S)), (Stage.OPPOSITE, (W,))]),
        (
            {N, W, S},
            S,
            [(Stage.PRIMARY, (S,)), (Stage.NEIGHBOUR, (W,)), (Stage.OPPOSITE, (N,))],
        ),
        ({N, W, S}, W, [(Stage.PRIMARY, (W,)), (Stage.NEIGHBOUR, (N, S))]),
        ({N}, N, [(Stage.PRIMARY, (N,))]),
        (set(), S, []),
    ],
)
def test_fallback_chain(configured, direction, chain):
    assert fallback_chain(direction, configured) == [*chain, (Stage.WEATHER, ())]


@pytest.mark.parametrize(
    ("direction", "failing", "stale", "temp", "stage", "ah", "ah_stage"),
    [
        (N, fail(), False, 13.0, Stage.PRIMARY, 8.04, Stage.PRIMARY),
        (
            N,
            fail((N, TEMPERATURE), (N, HUMIDITY)),
            False,
            14.5,
            Stage.NEIGHBOUR,
            8.07,
            Stage.NEIGHBOUR,
        ),
        (N, all_fail(N, W), False, 12.5, Stage.OPPOSITE, 8.34, Stage.OPPOSITE),
        (N, all_fail(N, W, S), False, 11.0, Stage.WEATHER, 7.99, Stage.WEATHER),
        (N, all_fail(N, W, S), True, None, Stage.NONE, None, Stage.NONE),
        (N, fail((N, HUMIDITY)), False, 13.0, Stage.PRIMARY, 8.07, Stage.NEIGHBOUR),
        (E, fail(), False, 12.75, Stage.NEIGHBOUR, 8.19, Stage.NEIGHBOUR),
        (
            E,
            fail((N, TEMPERATURE)),
            False,
            12.5,
            Stage.NEIGHBOUR,
            8.34,
            Stage.NEIGHBOUR,
        ),
    ],
)
def test_values(direction, failing, stale, temp, stage, ah, ah_stage):
    result = resolve_direction(
        direction, regions(failing), weather(stale=stale), NO_OFFSETS, NOW
    )
    assert result.temperature.stage is stage
    assert result.temperature.value == pytest.approx(temp, abs=0.01)
    assert result.absolute_humidity.stage is ah_stage
    assert result.absolute_humidity.value == pytest.approx(ah, abs=0.01)
    assert result.dew_point.stage is ah_stage


def test_regions_of_a_stage():
    result = resolve_direction(E, regions(), weather(), NO_OFFSETS, NOW)
    assert result.temperature.regions == (N, S)
    assert result.temperature.reason is None
    result = resolve_direction(
        E, regions(fail((N, TEMPERATURE))), None, NO_OFFSETS, NOW
    )
    assert result.temperature.regions == (S,)


def test_dew_point_neighbour_mean():
    result = resolve_direction(E, regions(), weather(), NO_OFFSETS, NOW)
    assert result.dew_point.value == pytest.approx(8.12, abs=0.01)


def test_pair_stage_fallback_when_a_source_is_fallback():
    result = resolve_direction(
        N, regions(fallback=fail((N, HUMIDITY))), weather(), NO_OFFSETS, NOW
    )
    assert result.temperature.stage is Stage.PRIMARY
    assert result.humidity.stage is Stage.FALLBACK
    assert result.absolute_humidity.stage is Stage.FALLBACK


def test_house_outdoor_all_regions():
    house = house_outdoor(regions(), weather(), NO_OFFSETS, NOW)
    assert house.value == pytest.approx(13.33, abs=0.01)
    assert (house.minimum, house.maximum) == (12.5, 14.5)
    assert house.per_region == {N: 13.0, S: 12.5, W: 14.5}
    assert house.stage is Stage.PRIMARY


def test_house_outdoor_stage_fallback_and_partial():
    house = house_outdoor(
        regions(fail((S, TEMPERATURE)), fallback=fail((N, TEMPERATURE))),
        weather(),
        NO_OFFSETS,
        NOW,
    )
    assert house.value == pytest.approx(13.75)
    assert house.stage is Stage.FALLBACK
    assert S not in house.per_region


def test_no_side():
    result = resolve_direction(None, regions(), weather(), NO_OFFSETS, NOW)
    for value in (
        result.temperature,
        result.humidity,
        result.pressure,
        result.absolute_humidity,
        result.dew_point,
    ):
        assert (value.value, value.stage) == (None, Stage.NONE)
        assert value.reason is OutdoorReason.NO_SIDE


def test_no_data_and_no_pair_reasons():
    failing = all_fail(N, W, S)
    result = resolve_direction(N, regions(failing), None, NO_OFFSETS, NOW)
    assert result.temperature.reason is OutdoorReason.NO_DATA
    assert result.absolute_humidity.reason is OutdoorReason.NO_PAIR
    assert result.dew_point.reason is OutdoorReason.NO_PAIR


def test_house_outdoor_nothing():
    house = house_outdoor(regions(all_fail(N, W, S)), None, NO_OFFSETS, NOW)
    assert (house.value, house.stage, house.per_region) == (None, Stage.NONE, {})


def learned(value: float) -> Offset:
    return Offset(value, timedelta(hours=8), NOW, value)


OFFSETS = WeatherOffsets(
    {
        (N, TEMPERATURE): learned(-2.0),
        (S, TEMPERATURE): learned(-1.5),
        (W, TEMPERATURE): learned(-3.5),
        (N, HUMIDITY): learned(9.0),
        (N, PRESSURE): learned(18.0),
    }
)


@pytest.mark.parametrize(
    ("direction", "temp", "humidity", "pressure", "ah"),
    [
        (N, 13.0, 71.0, 1003.0, 8.04),
        (E, 13.33, None, None, None),
    ],
)
def test_weather_offsets(direction, temp, humidity, pressure, ah):
    result = resolve_direction(
        direction, regions(all_fail(N, W, S)), weather(), OFFSETS, NOW
    )
    assert result.temperature.stage is Stage.WEATHER
    assert result.temperature.value == pytest.approx(temp, abs=0.01)
    if humidity is not None:
        assert result.humidity.value == pytest.approx(humidity)
        assert result.pressure.value == pytest.approx(pressure)
        assert result.absolute_humidity.value == pytest.approx(ah, abs=0.01)


def test_applied_offset_attribute():
    result = resolve_direction(N, regions(all_fail(N, W, S)), weather(), OFFSETS, NOW)
    assert result.temperature.offset == pytest.approx(-2.0)
    plain = resolve_direction(N, regions(), weather(), OFFSETS, NOW)
    assert plain.temperature.offset is None


def test_weather_offset_house_mean():
    house = house_outdoor(regions(all_fail(N, W, S)), weather(), OFFSETS, NOW)
    assert house.stage is Stage.WEATHER
    assert house.value == pytest.approx(13.33, abs=0.01)


def test_weather_without_learned_offsets():
    result = resolve_direction(
        N, regions(all_fail(N, W, S)), weather(), NO_OFFSETS, NOW
    )
    assert result.temperature.value == pytest.approx(11.0)
    assert result.humidity.value == pytest.approx(80.0)
    assert result.pressure.value == pytest.approx(1021.0)
    assert result.absolute_humidity.value == pytest.approx(7.99, abs=0.01)
    assert result.temperature.offset == 0.0


def test_corrected_humidity_is_clamped():
    offsets = WeatherOffsets({(N, HUMIDITY): learned(-30.0)})
    result = resolve_direction(N, regions(all_fail(N, W, S)), weather(), offsets, NOW)
    assert result.humidity.value == 100.0


def test_learning_gate():
    state = learn_weather_offsets({N: regions()[N]}, weather(), None, NOW)
    assert state.offsets[(N, TEMPERATURE)].learned == pytest.approx(-2.0)
    assert state.offsets[(N, HUMIDITY)].learned == pytest.approx(9.0)
    assert state.offsets[(N, PRESSURE)].learned == pytest.approx(18.0)
    assert set(state.offsets) == {(N, m) for m in Metric}


def test_learning_needs_own_value():
    own = regions(fail((N, HUMIDITY)))
    state = learn_weather_offsets({N: own[N]}, weather(), None, NOW)
    assert (N, HUMIDITY) not in state.offsets
    assert (N, TEMPERATURE) in state.offsets


def test_stale_weather_teaches_nothing():
    later = NOW + timedelta(minutes=1)
    state = learn_weather_offsets(
        {N: regions()[N]}, weather(stale=True), OFFSETS, later
    )
    assert state.offsets == {k: v for k, v in OFFSETS.offsets.items() if k[0] is N}
    assert learn_weather_offsets({N: regions()[N]}, None, None, NOW).offsets == {}


def test_removed_regions_drop_offsets():
    state = learn_weather_offsets({N: regions()[N]}, None, OFFSETS, NOW)
    assert {d for d, _ in state.offsets} == {N}


def test_learning_updates_moving_average():
    first = learn_weather_offsets({N: regions()[N]}, weather(), None, NOW)
    later = NOW + timedelta(minutes=10)
    warmer = Reading("weather.home", 12.0, Status.OK, later)
    changed = WeatherReadings(warmer, weather().humidity, weather().pressure)
    second = learn_weather_offsets({N: regions()[N]}, changed, first, later)
    # the average moves from -2.0 towards -1.0 without reaching it
    assert -2.0 < second.offsets[(N, TEMPERATURE)].learned < -1.0
