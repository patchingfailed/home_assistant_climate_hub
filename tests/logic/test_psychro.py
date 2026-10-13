"""Table cases of docs/logic.md §3."""

import pytest

from custom_components.climate_hub.logic.psychro import (
    absolute_humidity,
    dew_point,
    humidity_after_ventilating,
)


def _approx(expected, tolerance):
    return None if expected is None else pytest.approx(expected, abs=tolerance)


@pytest.mark.parametrize(
    ("t", "rh", "ah", "dp"),
    [
        (20, 50, 8.62, 9.26),
        (20, 60, 10.35, 12.00),
        (22, 65, 12.59, 15.12),
        (0, 80, 3.88, -3.04),
        (-10, 90, 2.13, -11.33),
        (30, 40, 12.11, 14.93),
        (25, 100, 22.98, 25.00),
        (25, 104, 22.98, 25.00),  # clamped
        (20, 0, None, None),
    ],
)
def test_absolute_humidity_and_dew_point(t, rh, ah, dp):
    assert absolute_humidity(t, rh) == _approx(ah, 0.01)
    assert dew_point(t, rh) == _approx(dp, 0.01)


@pytest.mark.parametrize(
    ("t_out", "rh_out", "t_room", "expected"),
    [
        (24, 70, 20, 89.3),  # scenario 12
        (5, 85, 21, 29.8),  # winter air dries
        (25, 80, 18, 122.8),  # condensation, not clamped
    ],
)
def test_humidity_after_ventilating(t_out, rh_out, t_room, expected):
    result = humidity_after_ventilating(t_room, dew_point(t_out, rh_out))
    assert result == pytest.approx(expected, abs=0.1)
