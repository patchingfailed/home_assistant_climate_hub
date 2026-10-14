"""Shared fixture house (docs/integration.md section 14).

A German-language house with floors, areas, devices and entities shaped like the
acceptance scenarios. Registry entries and states are created directly; one
``MockConfigEntry`` of domain ``test`` owns all devices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

PLATFORM = "test"

TEMPERATURE = "temperature"
HUMIDITY = "humidity"
PRESSURE = "pressure"
_UNITS = {TEMPERATURE: "°C", HUMIDITY: "%", PRESSURE: "hPa"}
_LABELS = {TEMPERATURE: "Temperatur", HUMIDITY: "Luftfeuchtigkeit", PRESSURE: "Druck"}


def _default_hourly() -> list[dict[str, Any]]:
    """24 hourly points from the current hour, 10-18 degC with a peak at 14:00."""
    start = dt_util.now().replace(minute=0, second=0, microsecond=0)
    points = []
    for i in range(24):
        moment = start + timedelta(hours=i)
        distance = abs(moment.hour - 14)
        distance = min(distance, 24 - distance)
        points.append(
            {
                "datetime": moment.isoformat(),
                "temperature": round(18.0 - distance * (8.0 / 12), 1),
                "condition": "cloudy",
            }
        )
    return points


def _default_daily() -> list[dict[str, Any]]:
    start = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
    return [
        {
            "datetime": (start + timedelta(days=i)).isoformat(),
            "temperature": 18.0,
            "templow": 10.0,
            "condition": "cloudy",
        }
        for i in range(7)
    ]


@dataclass(frozen=True)
class House:
    """IDs of everything ``build_house`` created."""

    config_entry: MockConfigEntry

    # Floors
    ground: str  # Erdgeschoss, level 0
    upper: str  # Obergeschoss, level 1
    outside: str  # Außen, no level

    # Areas
    living_room: str  # Wohnzimmer
    kitchen: str  # Küche
    conservatory: str  # Wintergarten
    bathroom: str  # Bad
    bedroom: str  # Schlafzimmer
    study: str  # Arbeitszimmer
    storage: str  # Abstellraum, no floor
    garden: str  # Garten
    yard: str  # Hof
    street: str  # Straße, no floor

    # Living room
    living_temp: str
    living_hum: str
    living_pressure: str
    living_air_temp: str
    living_thermostat: str
    living_leaf_1: str
    living_leaf_2: str
    living_bottom: str
    living_cover: str

    # Kitchen
    kitchen_temp: str
    kitchen_hum: str
    kitchen_thermostat: str
    fridge_temp: str
    printer_temp: str
    printer_switch: str
    kitchen_contact: str
    kitchen_contact_temp: str

    # Bathroom
    bath_temp: str
    bath_hum: str
    bath_window_text: str

    # Bedroom, study, conservatory, storage
    bedroom_temp: str
    study_temp: str
    study_hum: str
    study_door: str
    conservatory_window: str
    plug_switch: str
    plug_temp: str

    # Outdoor
    street_temp: str
    street_hum: str
    garden_temp: str
    garden_hum: str
    garden_pressure: str
    yard_temp: str

    # No area
    loose_window: str  # window contact device without area (scenario 8)
    loose_text: str  # text sensor without device and area
    template_temp: str  # template platform, no device, no area

    # Weather and sun
    weather: str
    sun: str

    _forecasts: dict[str, list[dict[str, Any]]] = field(repr=False, compare=False)

    def set_forecast(self, points: list[dict[str, Any]], hourly: bool = True) -> None:
        """Change what the fake ``weather.get_forecasts`` returns."""
        self._forecasts["hourly" if hourly else "daily"] = list(points)


def set_value(
    hass: HomeAssistant, entity_id: str, value: str | float, **attributes: Any
) -> None:
    """Set a state, keeping the existing attributes (``attributes`` override)."""
    old = hass.states.get(entity_id)
    merged = {**(old.attributes if old else {}), **attributes}
    hass.states.async_set(entity_id, str(value), merged)


class _Builder:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entry = MockConfigEntry(domain=PLATFORM, title="Fixture house")
        self.entry.add_to_hass(hass)
        self.areas = ar.async_get(hass)
        self.devices = dr.async_get(hass)
        self.entities = er.async_get(hass)

    def device(self, key: str, name: str, area_id: str | None) -> str:
        device = self.devices.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(PLATFORM, key)},
            name=name,
            manufacturer="Acme",
            model=name,
        )
        if area_id:
            self.devices.async_update_device(device.id, area_id=area_id)
        return device.id

    def entity(
        self,
        domain: str,
        object_id: str,
        state: str,
        *,
        name: str,
        device_id: str | None = None,
        platform: str = PLATFORM,
        device_class: str | None = None,
        unit: str | None = None,
        category: EntityCategory | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        """Register an entity and set its state; returns the entity ID."""
        registered = self.entities.async_get_or_create(
            domain,
            platform,
            object_id,
            suggested_object_id=object_id,
            config_entry=self.entry if platform == PLATFORM else None,
            device_id=device_id,
            entity_category=category,
            original_device_class=device_class,
            original_name=name,
            unit_of_measurement=unit,
        )
        attrs: dict[str, Any] = {"friendly_name": name, **(attributes or {})}
        if device_class:
            attrs["device_class"] = device_class
        if unit:
            attrs["unit_of_measurement"] = unit
        self.hass.states.async_set(registered.entity_id, state, attrs)
        return registered.entity_id

    def metric(
        self,
        object_id: str,
        value: float,
        metric: str,
        device_id: str | None,
        label: str,
        category: EntityCategory | None = None,
    ) -> str:
        return self.entity(
            "sensor",
            object_id,
            str(value),
            name=f"{label} {_LABELS[metric]}",
            device_id=device_id,
            device_class=metric,
            unit=_UNITS[metric],
            category=category,
            attributes={"state_class": "measurement"},
        )

    def thermostat(
        self,
        object_id: str,
        device_id: str,
        *,
        current: float,
        action: str,
        humidity: int | None,
    ) -> str:
        attrs: dict[str, Any] = {
            "current_temperature": current,
            "temperature": 21.0,
            "hvac_action": action,
            "hvac_modes": ["off", "heat"],
        }
        if humidity is not None:
            attrs["current_humidity"] = humidity
        return self.entity(
            "climate",
            object_id,
            "heat",
            name="Thermostat",
            device_id=device_id,
            attributes=attrs,
        )

    def contact(
        self, object_id: str, device_id: str, label: str, device_class: str = "window"
    ) -> str:
        return self.entity(
            "binary_sensor",
            object_id,
            "off",
            name=label,
            device_id=device_id,
            device_class=device_class,
        )


async def build_house(hass: HomeAssistant) -> House:
    """Create floors, areas, devices, entities, states, weather, sun, forecast."""
    b = _Builder(hass)

    floors = fr.async_get(hass)
    ground = floors.async_create("Erdgeschoss", level=0).floor_id
    upper = floors.async_create("Obergeschoss", level=1).floor_id
    outside = floors.async_create("Außen").floor_id

    def area(name: str, floor_id: str | None = None) -> str:
        return b.areas.async_create(name, floor_id=floor_id).id

    living_room = area("Wohnzimmer", ground)
    kitchen = area("Küche", ground)
    conservatory = area("Wintergarten", ground)
    bathroom = area("Bad", upper)
    bedroom = area("Schlafzimmer", upper)
    study = area("Arbeitszimmer", upper)
    storage = area("Abstellraum")
    garden = area("Garten", outside)
    yard = area("Hof", outside)
    street = area("Straße")

    # Living room
    dev = b.device("living_climate", "Klimasensor", living_room)
    living_temp = b.metric(
        "wohnzimmer_klimasensor_temperatur", 21.4, TEMPERATURE, dev, "Klimasensor"
    )
    living_hum = b.metric(
        "wohnzimmer_klimasensor_luftfeuchtigkeit", 48, HUMIDITY, dev, "Klimasensor"
    )
    living_pressure = b.metric(
        "wohnzimmer_klimasensor_druck", 1012, PRESSURE, dev, "Klimasensor"
    )
    dev = b.device("living_air", "Luftmesser", living_room)
    living_air_temp = b.metric(
        "wohnzimmer_luftmesser_temperatur", 21.7, TEMPERATURE, dev, "Luftmesser"
    )
    dev = b.device("living_thermostat", "Thermostat", living_room)
    living_thermostat = b.thermostat(
        "wohnzimmer_thermostat", dev, current=22.6, action="heating", humidity=50
    )
    dev = b.device("living_leaf_1", "Fensterkontakt Flügel 1", living_room)
    living_leaf_1 = b.contact("wohnzimmer_kontakt_fluegel_1", dev, "Kontakt Flügel 1")
    dev = b.device("living_leaf_2", "Fensterkontakt Flügel 2", living_room)
    living_leaf_2 = b.contact("wohnzimmer_kontakt_fluegel_2", dev, "Kontakt Flügel 2")
    dev = b.device("living_bottom", "Fensterkontakt unten", living_room)
    living_bottom = b.contact("wohnzimmer_kontakt_unten", dev, "Kontakt unten")
    dev = b.device("living_cover", "Rollladen", living_room)
    living_cover = b.entity(
        "cover",
        "wohnzimmer_rollladen",
        "open",
        name="Rollladen",
        device_id=dev,
        device_class="shutter",
        attributes={"current_position": 100},
    )

    # Kitchen
    dev = b.device("kitchen_climate", "Klimasensor", kitchen)
    kitchen_temp = b.metric(
        "kueche_klimasensor_temperatur", 20.7, TEMPERATURE, dev, "Klimasensor"
    )
    kitchen_hum = b.metric(
        "kueche_klimasensor_luftfeuchtigkeit", 57, HUMIDITY, dev, "Klimasensor"
    )
    dev = b.device("kitchen_thermostat", "Thermostat", kitchen)
    kitchen_thermostat = b.thermostat(
        "kueche_thermostat", dev, current=21.2, action="idle", humidity=None
    )
    dev = b.device("fridge", "Kühlschrank-Sensor", kitchen)
    fridge_temp = b.metric(
        "kuehlschrank_temperatur", 6.9, TEMPERATURE, dev, "Kühlschrank"
    )
    dev = b.device("printer", "3D-Drucker", kitchen)
    printer_temp = b.metric("drucker_temperatur", 45, TEMPERATURE, dev, "Drucker")
    printer_switch = b.entity(
        "switch", "drucker_schalter", "off", name="Drucker Schalter", device_id=dev
    )
    dev = b.device("kitchen_contact", "Fensterkontakt", kitchen)
    kitchen_contact = b.contact("kueche_fensterkontakt", dev, "Fensterkontakt")
    kitchen_contact_temp = b.metric(
        "kueche_fensterkontakt_temperatur", 19.5, TEMPERATURE, dev, "Fensterkontakt"
    )

    # Bathroom
    dev = b.device("bath_climate", "Klimasensor", bathroom)
    bath_temp = b.metric(
        "bad_klimasensor_temperatur", 19.9, TEMPERATURE, dev, "Klimasensor"
    )
    bath_hum = b.metric(
        "bad_klimasensor_luftfeuchtigkeit", 66, HUMIDITY, dev, "Klimasensor"
    )
    # A plain template-like text sensor: no device, its area is set on the entity.
    bath_window_text = b.entity(
        "sensor", "bad_fenster", "zu", name="Bad Fenster", platform="template"
    )
    b.entities.async_update_entity(bath_window_text, area_id=bathroom)

    # Bedroom
    dev = b.device("bedroom_air", "Luftmesser", bedroom)
    bedroom_temp = b.metric(
        "schlafzimmer_luftmesser_temperatur", 18.9, TEMPERATURE, dev, "Luftmesser"
    )

    # Study
    dev = b.device("study_climate", "Klimasensor", study)
    study_temp = b.metric(
        "arbeitszimmer_klimasensor_temperatur", 20.5, TEMPERATURE, dev, "Klimasensor"
    )
    study_hum = b.metric(
        "arbeitszimmer_klimasensor_luftfeuchtigkeit", 52, HUMIDITY, dev, "Klimasensor"
    )
    dev = b.device("study_door", "Türkontakt", study)
    study_door = b.contact("arbeitszimmer_tuerkontakt", dev, "Türkontakt", "door")

    # Conservatory
    dev = b.device("conservatory_contact", "Fensterkontakt", conservatory)
    conservatory_window = b.contact(
        "wintergarten_fensterkontakt", dev, "Fensterkontakt"
    )

    # Storage
    dev = b.device("plug", "Zwischenstecker", storage)
    plug_switch = b.entity(
        "switch", "abstellraum_stecker", "on", name="Zwischenstecker", device_id=dev
    )
    plug_temp = b.metric(
        "abstellraum_stecker_temperatur",
        31.0,
        TEMPERATURE,
        dev,
        "Zwischenstecker",
        category=EntityCategory.DIAGNOSTIC,
    )

    # Outdoor
    dev = b.device("street_sensor", "Außensensor", street)
    street_temp = b.metric(
        "strasse_aussensensor_temperatur", 13.0, TEMPERATURE, dev, "Außensensor"
    )
    street_hum = b.metric(
        "strasse_aussensensor_luftfeuchtigkeit", 71, HUMIDITY, dev, "Außensensor"
    )
    dev = b.device("garden_sensor", "Außensensor", garden)
    garden_temp = b.metric(
        "garten_aussensensor_temperatur", 12.5, TEMPERATURE, dev, "Außensensor"
    )
    garden_hum = b.metric(
        "garten_aussensensor_luftfeuchtigkeit", 76, HUMIDITY, dev, "Außensensor"
    )
    garden_pressure = b.metric(
        "garten_aussensensor_druck", 1013, PRESSURE, dev, "Außensensor"
    )
    dev = b.device("yard_sensor", "Außensensor", yard)
    yard_temp = b.metric(
        "hof_aussensensor_temperatur", 14.5, TEMPERATURE, dev, "Außensensor"
    )

    # No area
    dev = b.device("loose_contact", "Fensterkontakt", None)
    loose_window = b.contact("lose_fensterkontakt", dev, "Fensterkontakt")
    loose_text = b.entity(
        "sensor",
        "fenster_text",
        "geschlossen",
        name="Fenster Text",
        platform="template",
    )
    template_temp = b.entity(
        "sensor",
        "vorlage_temperatur",
        "20.0",
        name="Vorlage Temperatur",
        platform="template",
        device_class=TEMPERATURE,
        unit="°C",
        attributes={"state_class": "measurement"},
    )

    # Weather, sun, fake forecast service
    weather = "weather.home"
    hass.states.async_set(
        weather,
        "cloudy",
        {
            "friendly_name": "Home",
            "temperature": 12.0,
            "humidity": 80,
            "pressure": 1015,
            "cloud_coverage": 90,
            "temperature_unit": "°C",
            "pressure_unit": "hPa",
            "supported_features": WeatherEntityFeature.FORECAST_HOURLY
            | WeatherEntityFeature.FORECAST_DAILY,
        },
    )
    sun = "sun.sun"
    hass.states.async_set(
        sun,
        "above_horizon",
        {"friendly_name": "Sun", "azimuth": 180, "elevation": 35},
    )

    forecasts = {"hourly": _default_hourly(), "daily": _default_daily()}

    async def _get_forecasts(call: ServiceCall) -> dict[str, Any]:
        kind = call.data.get("type", "hourly")
        return {
            entity_id: {"forecast": forecasts.get(kind, [])}
            for entity_id in call.data["entity_id"]
        }

    hass.services.async_register(
        "weather",
        "get_forecasts",
        _get_forecasts,
        supports_response=SupportsResponse.ONLY,
    )

    return House(
        config_entry=b.entry,
        ground=ground,
        upper=upper,
        outside=outside,
        living_room=living_room,
        kitchen=kitchen,
        conservatory=conservatory,
        bathroom=bathroom,
        bedroom=bedroom,
        study=study,
        storage=storage,
        garden=garden,
        yard=yard,
        street=street,
        living_temp=living_temp,
        living_hum=living_hum,
        living_pressure=living_pressure,
        living_air_temp=living_air_temp,
        living_thermostat=living_thermostat,
        living_leaf_1=living_leaf_1,
        living_leaf_2=living_leaf_2,
        living_bottom=living_bottom,
        living_cover=living_cover,
        kitchen_temp=kitchen_temp,
        kitchen_hum=kitchen_hum,
        kitchen_thermostat=kitchen_thermostat,
        fridge_temp=fridge_temp,
        printer_temp=printer_temp,
        printer_switch=printer_switch,
        kitchen_contact=kitchen_contact,
        kitchen_contact_temp=kitchen_contact_temp,
        bath_temp=bath_temp,
        bath_hum=bath_hum,
        bath_window_text=bath_window_text,
        bedroom_temp=bedroom_temp,
        study_temp=study_temp,
        study_hum=study_hum,
        study_door=study_door,
        conservatory_window=conservatory_window,
        plug_switch=plug_switch,
        plug_temp=plug_temp,
        street_temp=street_temp,
        street_hum=street_hum,
        garden_temp=garden_temp,
        garden_hum=garden_hum,
        garden_pressure=garden_pressure,
        yard_temp=yard_temp,
        loose_window=loose_window,
        loose_text=loose_text,
        template_temp=template_temp,
        weather=weather,
        sun=sun,
        _forecasts=forecasts,
    )
