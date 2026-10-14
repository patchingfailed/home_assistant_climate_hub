"""Table cases of docs/logic.md §11."""

import pytest

from custom_components.climate_hub.logic.prefill import (
    AreaInfo,
    EntityInfo,
    Exclusion,
    Scope,
    Tier,
    classify,
    follow_devices,
    new_sources,
    propose_rooms,
    suggest_climate_devices,
    suggest_metric_list,
    suggest_sources,
)
from custom_components.climate_hub.logic.sources import Metric

T, H, P = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE
KITCHEN = "kueche"


def ent(
    entity_id,
    name=None,
    *,
    domain=None,
    device_class=None,
    platform="zha",
    category=None,
    device="d",
    area=KITCHEN,
    value=21.0,
    humidity=False,
):
    return EntityInfo(
        entity_id=entity_id,
        name=name or entity_id,
        domain=domain or entity_id.split(".")[0],
        device_class=device_class,
        platform=platform,
        category=category,
        device_id=device,
        area_id=area,
        value=value,
        has_current_humidity=humidity,
    )


def temp(entity_id, name=None, **kw):
    return ent(entity_id, name, device_class="temperature", **kw)


def hum(entity_id, name=None, **kw):
    return ent(entity_id, name, device_class="humidity", **{"value": 50.0, **kw})


def pres(entity_id, name=None, **kw):
    return ent(entity_id, name, device_class="pressure", **{"value": 1013.0, **kw})


CLIMATE_SENSOR = [
    temp("sensor.cs_t", "Climate sensor", device="cs"),
    hum("sensor.cs_h", "Climate sensor humidity", device="cs"),
    pres("sensor.cs_p", "Climate sensor pressure", device="cs"),
]
AIR_METER = [
    temp("sensor.am_t", "Air meter", device="am"),
    hum("sensor.am_h", "Air meter humidity", device="am"),
]
PROBE = [
    temp("sensor.probe_t", "Probe", device="probe", platform="esphome"),
    ent(
        "button.probe_restart",
        category="diagnostic",
        device="probe",
        platform="esphome",
    ),
]
FRIDGE = [temp("sensor.fridge_t", "Fridge sensor", device="fridge", value=6.9)]
PRINTER = [
    temp("sensor.printer_nozzle", device="printer", value=210.0),
    temp("sensor.printer_bed", device="printer", value=60.0),
    temp("sensor.printer_chamber", device="printer", value=30.0),
]
WINDOW = [
    temp("sensor.window_t", device="window"),
    ent("binary_sensor.window", device_class="window", device="window"),
]
MOTION = [
    temp("sensor.motion_t", device="motion"),
    ent("binary_sensor.motion", device_class="motion", device="motion"),
]
PLUG = [
    temp("sensor.plug_t", device="plug", category="diagnostic"),
    ent("switch.plug", device="plug"),
]
SETPOINT = [temp("sensor.setpoint", device="tpl", platform="template")]
DEW_POINT = [temp("sensor.dew", device=None, platform="thermal_comfort")]
NO_DEVICE = [temp("sensor.nodev_t", device=None)]
THERMOSTAT = [
    ent("climate.thermostat", "Thermostat", device="th", humidity=True, value=21.0)
]
AIR_CON = [
    ent("climate.ac", "Air conditioner", device="ac", value=22.0),
    temp("sensor.ac_outdoor", device="ac", value=18.0),
]
OWN = [temp("sensor.hub_t", device="hub", platform="climate_hub")]
NO_AREA = [
    temp("sensor.na_t", "Unassigned", device="na", area=None),
    hum("sensor.na_h", device="na", area=None),
]

KITCHEN_SET = [
    *CLIMATE_SENSOR,
    *AIR_METER,
    *PROBE,
    *FRIDGE,
    *PRINTER,
    *WINDOW,
    *MOTION,
    *PLUG,
    *SETPOINT,
    *DEW_POINT,
    *NO_DEVICE,
    *THERMOSTAT,
    *OWN,
    *NO_AREA,
]


def classify_in(entity_id, entities, metric=T, scope=Scope.ROOM):
    entity = next(e for e in entities if e.entity_id == entity_id)
    group = [
        e for e in entities if entity.device_id and e.device_id == entity.device_id
    ]
    return classify(entity, group, metric, scope)


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.cs_t", Tier.CLIMATE_GRADE),
        ("sensor.am_t", Tier.CLIMATE_GRADE),
        ("sensor.probe_t", Tier.SINGLE_VALUE),
        ("sensor.fridge_t", Exclusion.IMPLAUSIBLE),
        ("sensor.printer_nozzle", Exclusion.SEVERAL_TEMPERATURES),
        ("sensor.printer_bed", Exclusion.SEVERAL_TEMPERATURES),
        ("sensor.printer_chamber", Exclusion.SEVERAL_TEMPERATURES),
        ("sensor.window_t", Exclusion.CONTACT),
        ("sensor.motion_t", Exclusion.MOTION),
        ("sensor.plug_t", Exclusion.DIAGNOSTIC),
        ("sensor.setpoint", Exclusion.HELPER),
        ("sensor.dew", Exclusion.HELPER),
        ("sensor.nodev_t", Exclusion.NO_DEVICE),
        ("climate.thermostat", Tier.CLIMATE_ENTITY),
        ("sensor.hub_t", None),
        ("sensor.na_t", Tier.CLIMATE_GRADE),
        ("sensor.cs_h", None),
        ("switch.plug", None),
    ],
)
def test_kitchen_temperature(entity_id, expected):
    assert classify_in(entity_id, KITCHEN_SET) == expected


def test_air_conditioner():
    entities = [*AIR_CON]
    assert classify_in("climate.ac", entities) == Tier.CLIMATE_ENTITY
    assert classify_in("sensor.ac_outdoor", entities) == Exclusion.SECONDARY


def test_climate_implausible_in_room():
    cold = [ent("climate.c", device="c", value=3.0)]
    assert classify_in("climate.c", cold) == Exclusion.IMPLAUSIBLE


def test_unknown_value_is_plausible():
    probe = [temp("sensor.x", device="x", value=None)]
    assert classify_in("sensor.x", probe) == Tier.SINGLE_VALUE


def test_prefill_order():
    suggestion = suggest_sources(KITCHEN, KITCHEN_SET, T, Scope.ROOM)
    assert suggestion.sources == (
        "sensor.am_t",
        "sensor.cs_t",
        "sensor.probe_t",
        "climate.thermostat",
    )
    assert ("sensor.fridge_t", Exclusion.IMPLAUSIBLE) in suggestion.excluded
    assert ("sensor.plug_t", Exclusion.DIAGNOSTIC) in suggestion.excluded
    assert all(i != "sensor.hub_t" for i, _ in suggestion.excluded)
    assert all(i != "sensor.na_t" for i, _ in suggestion.excluded)


def test_prefill_order_by_name_then_id():
    entities = [
        temp("sensor.b", "Same", device="b"),
        temp("sensor.a", "Same", device="a"),
        temp("sensor.c", "alpha", device="c"),
    ]
    assert suggest_sources(KITCHEN, entities, T, Scope.ROOM).sources == (
        "sensor.c",
        "sensor.a",
        "sensor.b",
    )


def test_region_scope():
    region = "garten"
    entities = [
        temp("sensor.out_t", "Outside", device="o", area=region, value=-15.0),
        temp("sensor.hot_t", "Hot", device="h", area=region, value=70.0),
        ent("climate.ac", device="ac", area=region, value=22.0),
        temp("sensor.ac_t", device="ac", area=region, value=18.0),
    ]
    assert (
        classify_in("climate.ac", entities, scope=Scope.REGION) == Exclusion.SECONDARY
    )
    assert (
        classify_in("sensor.out_t", entities, scope=Scope.REGION) == Tier.SINGLE_VALUE
    )
    assert classify_in("sensor.out_t", entities) == Exclusion.IMPLAUSIBLE
    assert classify_in("sensor.hot_t", entities, scope=Scope.REGION) == (
        Exclusion.IMPLAUSIBLE
    )
    assert suggest_sources(region, entities, T, Scope.REGION).sources == (
        "sensor.out_t",
    )


@pytest.mark.parametrize(
    ("entity_id", "metric", "scope", "expected"),
    [
        ("sensor.cs_h", H, Scope.ROOM, Tier.CLIMATE_GRADE),
        ("sensor.cs_p", P, Scope.ROOM, Tier.CLIMATE_GRADE),
        ("sensor.am_h", H, Scope.ROOM, Tier.CLIMATE_GRADE),
        ("sensor.na_h", H, Scope.ROOM, Tier.CLIMATE_GRADE),
        ("climate.thermostat", H, Scope.ROOM, Tier.CLIMATE_ENTITY),
        ("climate.thermostat", H, Scope.REGION, None),
        ("climate.thermostat", P, Scope.ROOM, None),
        ("sensor.cs_t", H, Scope.ROOM, None),
    ],
)
def test_humidity_and_pressure(entity_id, metric, scope, expected):
    assert classify_in(entity_id, KITCHEN_SET, metric, scope) == expected


def test_humidity_only_device_is_tier_2_and_plausibility():
    entities = [
        hum("sensor.h_only", device="x"),
        hum("sensor.h_bad", device="y", value=130.0),
        pres("sensor.p_bad", device="z", value=500.0),
    ]
    assert classify_in("sensor.h_only", entities, H) == Tier.SINGLE_VALUE
    assert classify_in("sensor.h_bad", entities, H) == Exclusion.IMPLAUSIBLE
    assert classify_in("sensor.p_bad", entities, P) == Exclusion.IMPLAUSIBLE


def test_follow_devices():
    sources = ["sensor.cs_t", "sensor.am_t", "climate.thermostat"]
    assert follow_devices(sources, KITCHEN_SET, H) == [
        "sensor.cs_h",
        "sensor.am_h",
        "climate.thermostat",
    ]
    assert follow_devices(sources, KITCHEN_SET, P) == ["sensor.cs_p"]


def test_follow_skips_helpers_diagnostics_and_duplicates():
    entities = [
        temp("sensor.t", device="x"),
        hum("sensor.h_ok", device="x"),
        hum("sensor.h_diag", device="x", category="diagnostic"),
        hum("sensor.h_tpl", device="x", platform="template"),
    ]
    assert follow_devices(["sensor.t", "sensor.t", "sensor.unknown"], entities, H) == [
        "sensor.h_ok"
    ]
    assert follow_devices(["sensor.t"], entities, T) == []


def test_metric_list_follows():
    sources = ["sensor.cs_t", "climate.thermostat"]
    assert suggest_metric_list(sources, KITCHEN, KITCHEN_SET, H, Scope.ROOM) == []


def test_metric_list_prefilled_when_follow_is_empty():
    entities = [*NO_DEVICE, hum("sensor.lonely_h", "Lonely", device="l")]
    assert suggest_metric_list(
        ["sensor.nodev_t"], KITCHEN, entities, H, Scope.ROOM
    ) == ["sensor.lonely_h"]


def test_climate_devices():
    entities = [*AIR_CON, *THERMOSTAT, *NO_AREA, ent("climate.other", area="bad")]
    assert suggest_climate_devices(KITCHEN, entities) == [
        "climate.ac",
        "climate.thermostat",
    ]
    own = [ent("climate.hub", platform="climate_hub")]
    assert suggest_climate_devices(KITCHEN, own) == []


def test_new_sources():
    base = ["sensor.am_t", "sensor.cs_t", "sensor.probe_t", "climate.thermostat"]
    assert new_sources(KITCHEN, KITCHEN_SET, T, Scope.ROOM, [], []) == base
    assert new_sources(
        KITCHEN, KITCHEN_SET, T, Scope.ROOM, ["sensor.am_t"], ["sensor.probe_t"]
    ) == ["sensor.cs_t", "climate.thermostat"]
    # region scope: no tier 3, the fridge value is plausible outdoors
    region = new_sources(KITCHEN, KITCHEN_SET, T, Scope.REGION, [], [])
    assert "climate.thermostat" not in region
    assert "sensor.fridge_t" in region


def _room(area_id, floor, level, *, climate):
    area = AreaInfo(area_id, area_id.capitalize(), floor, level)
    items = [temp(f"sensor.{area_id}_t", device=area_id, area=area_id)]
    if climate:
        items.append(ent(f"climate.{area_id}", device=f"c_{area_id}", area=area_id))
    return area, items


def test_propose_rooms_precheck_and_order():
    rooms = [
        _room("wohnzimmer", "Erdgeschoss", 0, climate=True),
        _room("bad", "Erdgeschoss", 0, climate=False),
        _room("garten", "Außen", None, climate=False),
        _room("terrasse", "Außenbereich", None, climate=False),
        _room("strasse", None, None, climate=False),
        _room("werkstatt", None, None, climate=True),
    ]
    areas = [a for a, _ in rooms]
    entities = [e for _, items in rooms for e in items]
    proposal = propose_rooms(areas, entities, frozenset({"außen", "garten"}))
    assert dict(proposal) == {
        "wohnzimmer": True,
        "bad": True,
        "garten": False,
        "terrasse": False,
        "strasse": False,
        "werkstatt": True,
    }
    assert [a for a, _ in proposal] == [
        "bad",
        "wohnzimmer",
        "garten",
        "terrasse",
        "strasse",
        "werkstatt",
    ]


def test_propose_rooms_floor_order_and_filter():
    areas = [
        AreaInfo("a", "A", "Keller", -1),
        AreaInfo("b", "B", "Dach", None),
        AreaInfo("c", "C", "OG", 1),
        AreaInfo("d", "D", "OG", 1),
        AreaInfo("e", "E", None, None),
        AreaInfo("plug", "Plug only", "OG", 1),
    ]
    entities = [
        temp(f"sensor.{i}_t", device=i, area=i) for i in ("a", "b", "c", "d", "e")
    ]
    entities.append(
        temp("sensor.plug_t", device="p", area="plug", category="diagnostic")
    )
    proposal = propose_rooms(areas, entities, frozenset())
    assert [a for a, _ in proposal] == ["a", "c", "d", "b", "e"]
    assert [p for _, p in proposal] == [True, True, True, True, False]


@pytest.mark.parametrize(
    ("entities", "expected"),
    [
        # Only a sensor without a device: pre-filled as the last resort.
        (NO_DEVICE, ("sensor.nodev_t",)),
        # A real source wins; the device-less sensor stays excluded.
        ([*CLIMATE_SENSOR, *NO_DEVICE], ("sensor.cs_t",)),
        # Without a device: device-less first, then derived values.
        ([*SETPOINT, *NO_DEVICE], ("sensor.nodev_t", "sensor.setpoint")),
        # Implausible and diagnostic values never give way.
        ([temp("sensor.nodev_fridge", device=None, value=6.0)], ()),
        (PLUG, ()),
        # A device-less thermostat comes last.
        (
            [ent("climate.nodev", device=None), *NO_DEVICE],
            ("sensor.nodev_t", "climate.nodev"),
        ),
    ],
)
def test_last_resort_without_device(entities, expected):
    assert suggest_sources(KITCHEN, entities, T, Scope.ROOM).sources == expected


def test_last_resort_skips_climate_in_regions():
    entities = [ent("climate.nodev", device=None)]
    assert suggest_sources(KITCHEN, entities, T, Scope.REGION).sources == ()
