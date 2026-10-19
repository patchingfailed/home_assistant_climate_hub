"""Table cases of docs/logic.md §16: source labels, spread and setpoint deviation."""

import pytest

from custom_components.climate_hub.logic.const import HUMIDITY_WORDS, TEMPERATURE_WORDS
from custom_components.climate_hub.logic.readings import (
    Setpoint,
    labels,
    setpoint_deviation,
    spread,
)
from custom_components.climate_hub.logic.recommendation import ClimateDevice
from custom_components.climate_hub.logic.sources import Candidate, Status


@pytest.mark.parametrize(
    ("name", "area", "words", "expected"),
    [
        ("Wetter Arbeitszimmer Temp", "Arbeitszimmer", TEMPERATURE_WORDS, "Wetter"),
        (
            "Luftmeter Arbeitszimmer Temperatur",
            "Arbeitszimmer",
            TEMPERATURE_WORDS,
            "Luftmeter",
        ),
        ("schlafzimmer_bett_temp", "Schlafzimmer", TEMPERATURE_WORDS, "Bett"),
        ("Arbeitszimmer", "Arbeitszimmer", TEMPERATURE_WORDS, "Arbeitszimmer"),
        ("Wohnzimmer-Sensor Temperatur", "Wohnzimmer", TEMPERATURE_WORDS, "Sensor"),
        ("Tempo Sensor", "Küche", TEMPERATURE_WORDS, "Tempo Sensor"),
        ("Sensor Tempera", "Küche", TEMPERATURE_WORDS, "Sensor"),
        ("Wetter Badezimmer Feuchte", "Badezimmer", HUMIDITY_WORDS, "Wetter"),
        (
            "Luftmeter Badezimmer Luftfeuchtigkeit",
            "Badezimmer",
            HUMIDITY_WORDS,
            "Luftmeter",
        ),
        ("  Sensor RH ", "Küche", HUMIDITY_WORDS, "Sensor"),
        ("Sensor Rhein", "Küche", HUMIDITY_WORDS, "Sensor Rhein"),
        ("  Temperatur ", "Küche", TEMPERATURE_WORDS, "Temperatur"),
    ],
)
def test_single_label(name, area, words, expected):
    assert labels([("sensor.a", name)], [area], words) == {"sensor.a": expected}


def test_labels_keep_input_order():
    names = [("sensor.z", "Zed Raum Temp"), ("sensor.a", "Alpha Raum Temp")]
    result = labels(names, ["Raum"], TEMPERATURE_WORDS)
    assert list(result) == ["sensor.z", "sensor.a"]
    assert result == {"sensor.z": "Zed", "sensor.a": "Alpha"}


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (
            [
                ("sensor.a", "Sensor Küche Temp"),
                ("sensor.b", "Sensor Küche Temperatur"),
            ],
            {"sensor.a": "Sensor Küche Temp", "sensor.b": "Sensor Küche Temperatur"},
        ),
        (
            [("sensor.a", "Sensor Küche Temp"), ("sensor.b", "Sensor Küche Temp")],
            {"sensor.a": "sensor.a", "sensor.b": "sensor.b"},
        ),
        (
            [
                ("sensor.a", "Sensor Küche Temp"),
                ("sensor.b", "Sensor Küche Temp"),
                ("sensor.c", "Fenster Küche Temp"),
            ],
            {"sensor.a": "sensor.a", "sensor.b": "sensor.b", "sensor.c": "Fenster"},
        ),
    ],
)
def test_label_collisions(names, expected):
    assert labels(names, ["Küche"], TEMPERATURE_WORDS) == expected


def cand(entity_id, value, status=Status.OK):
    return Candidate(entity_id, status, value, None, False)


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        ([cand("sensor.a", 21.0), cand("sensor.b", 22.5)], 1.5),
        ([cand("sensor.a", 21.0), cand("climate.x", 23.0)], 2.0),
        (
            [cand("climate.x", 25.0), cand("sensor.a", 21.0), cand("sensor.b", 22.0)],
            1.0,
        ),
        ([cand("sensor.a", 21.0), cand("sensor.b", None, Status.STALE)], None),
        ([cand("sensor.a", 21.0)], None),
        ([cand("climate.x", 21.0)], None),
        ([], None),
    ],
)
def test_spread(candidates, expected):
    assert spread(candidates) == expected


def dev(mode, **kwargs):
    return ClimateDevice(None, mode, **kwargs)


@pytest.mark.parametrize(
    ("t_room", "devices", "expected"),
    [
        (
            20.0,
            [("climate.a", dev("heat", target=21.5))],
            Setpoint("climate.a", 21.5, 21.5, -1.5),
        ),
        (
            23.0,
            [("climate.a", dev("cool", target=21.5))],
            Setpoint("climate.a", 21.5, 21.5, 1.5),
        ),
        (
            21.5,
            [("climate.a", dev("auto", target=21.5))],
            Setpoint("climate.a", 21.5, 21.5, 0.0),
        ),
        (
            20.0,
            [
                ("climate.a", dev("off", target=25.0)),
                ("climate.b", dev("heat", target=22.0)),
            ],
            Setpoint("climate.b", 22.0, 22.0, -2.0),
        ),
        (
            20.0,
            [("climate.a", dev("dry", target=25.0))],
            Setpoint(None, None, None, None),
        ),
        (
            20.0,
            [("climate.a", dev("fan_only", target=25.0))],
            Setpoint(None, None, None, None),
        ),
        (
            22.0,
            [("climate.a", dev("heat_cool", target_low=20.0, target_high=24.0))],
            Setpoint("climate.a", 20.0, 24.0, 0.0),
        ),
        (
            18.0,
            [("climate.a", dev("heat_cool", target_low=20.0, target_high=24.0))],
            Setpoint("climate.a", 20.0, 24.0, -2.0),
        ),
        (
            26.0,
            [("climate.a", dev("heat_cool", target_low=20.0, target_high=24.0))],
            Setpoint("climate.a", 20.0, 24.0, 2.0),
        ),
        (
            26.0,
            [("climate.a", dev("heat_cool", target_low=24.0, target_high=20.0))],
            Setpoint("climate.a", 20.0, 24.0, 2.0),
        ),
        (
            20.0,
            [("climate.a", dev("heat")), ("climate.b", dev("heat", target=22.0))],
            Setpoint("climate.b", 22.0, 22.0, -2.0),
        ),
        (
            20.0,
            [("climate.a", dev("heat", target_low=20.0))],
            Setpoint(None, None, None, None),
        ),
        (20.0, [], Setpoint(None, None, None, None)),
        (
            None,
            [("climate.a", dev("heat", target=22.0))],
            Setpoint("climate.a", 22.0, 22.0, None),
        ),
    ],
)
def test_setpoint_deviation(t_room, devices, expected):
    assert setpoint_deviation(t_room, devices) == expected
