"""Psychrometrics (docs/logic.md §3; R10, R13, O6).

Magnus formula over water (Alduchov and Eskridge 1996) for all temperatures, also
below 0 °C: weather services report relative humidity over water.
"""

import math

_MAGNUS_A = 6.1094  # hPa
_MAGNUS_B = 17.625
_MAGNUS_C = 243.04  # °C
_VAPOUR_DENSITY = 216.68  # g·K/(m³·hPa), water vapour as an ideal gas
_KELVIN = 273.15


def _saturation_vapour_pressure(t: float) -> float:
    return _MAGNUS_A * math.exp(_MAGNUS_B * t / (_MAGNUS_C + t))


def _vapour_pressure(t: float, rh: float) -> float | None:
    if rh <= 0:
        return None
    return _saturation_vapour_pressure(t) * min(rh, 100.0) / 100.0


def absolute_humidity(t: float, rh: float) -> float | None:
    """Absolute humidity in g/m³; `None` at `rh <= 0`, `rh` above 100 % is clamped."""
    vp = _vapour_pressure(t, rh)
    if vp is None:
        return None
    return _VAPOUR_DENSITY * vp / (_KELVIN + t)


def dew_point(t: float, rh: float) -> float | None:
    """Dew point in °C; `None` at `rh <= 0`, `rh` above 100 % is clamped."""
    vp = _vapour_pressure(t, rh)
    if vp is None:
        return None
    gamma = math.log(vp / _MAGNUS_A)
    return _MAGNUS_C * gamma / (_MAGNUS_B - gamma)


def humidity_after_ventilating(t_room: float, dew_point_out: float) -> float:
    """Relative humidity in % that outside air reaches at room temperature (R13).

    Not clamped: above 100 % means the air condenses in the room.
    """
    saturated = _saturation_vapour_pressure(t_room)
    return 100.0 * _saturation_vapour_pressure(dew_point_out) / saturated
