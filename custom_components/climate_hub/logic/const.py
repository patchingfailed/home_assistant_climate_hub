"""Constants of the pure logic (docs/logic.md §13).

`DEFAULT_*` values are defaults of hub options or number entities; everything else
is fixed (D14).
"""

from datetime import timedelta

# Sources and offsets (§4)
DEFAULT_MAX_AGE = timedelta(minutes=40)
WEATHER_MAX_AGE = timedelta(hours=2)
OFFSET_TIME_CONSTANT = timedelta(hours=8)
OFFSET_SAMPLE_CAP = timedelta(minutes=30)
OFFSET_LEARNED_AFTER = timedelta(hours=1)
OFFSET_GLIDE = timedelta(minutes=60)

# Value ranges: clamping (§4, §5) and plausibility at setup (§11)
HUMIDITY_RANGE = (0.0, 100.0)
PRESSURE_RANGE = (800.0, 1100.0)
ROOM_TEMPERATURE_RANGE = (8.0, 40.0)
REGION_TEMPERATURE_RANGE = (-40.0, 60.0)

# Comfort (§6)
DEFAULT_COMFORT_MIN = 20.0
DEFAULT_COMFORT_MAX = 24.0
POSITION_HYSTERESIS = 0.3
RELATION_ENTER = 0.5
RELATION_EXIT = 0.25
DRYNESS_ENTER = 1.0
DRYNESS_EXIT = 0.5
TREND_WINDOW = timedelta(minutes=60)
TREND_MIN_SPAN = timedelta(minutes=30)
TREND_SAMPLE_INTERVAL = timedelta(minutes=1)
TREND_ENTER = 0.5  # K/h
TREND_EXIT = 0.25  # K/h

# Strategy and forecast bias (§7)
DEFAULT_STRATEGY_THRESHOLD = 2.0
STRATEGY_HYSTERESIS = 0.5
FORECAST_HORIZON = timedelta(hours=24)
FORECAST_MIN_POINTS = 12
BIAS_WEIGHT = 0.25
BIAS_MIN_SAMPLES = 3
BIAS_CLAMP = 5.0
BIAS_MIN_COVERAGE = timedelta(hours=18)
BIAS_MIN_DAY_POINTS = 18
BIAS_COVERAGE_STEP_CAP = timedelta(minutes=10)

# Windows (§8)
CONTACT_DEBOUNCE = timedelta(seconds=5)

# Recommendation (§9)
DEFAULT_HUMIDITY_THRESHOLD = 60.0
# Points below the humidity threshold: the humidity goal ends, the guard releases
HUMIDITY_RELEASE = 5.0
DEFAULT_BURST_DURATION = timedelta(minutes=10)
BURST_PAUSE = timedelta(hours=1)
PRE_COOL_START = 0.5  # °C above the comfort minimum

# Cover (§10)
SUN_MIN_ELEVATION = 10.0
SUN_MAX_ANGLE = 60.0
SUN_MAX_CLOUDS = 70.0
NIGHT_ELEVATION = 0.0
HEAT_RISK_ENTER = 0.5  # °C below the comfort maximum
HEAT_RISK_EXIT = 1.0  # °C below the comfort maximum
COVER_HOLD = timedelta(minutes=15)
COVER_CLOSED_POSITION = 50

# House (§12)
DEFAULT_REPAIR_DELAY = timedelta(hours=6)

# Readings (§16)
TEMPERATURE_WORDS = frozenset({"temperature", "temperatur", "temp"})
HUMIDITY_WORDS = frozenset(
    {"humidity", "luftfeuchtigkeit", "luftfeuchte", "feuchtigkeit", "feuchte", "rh"}
)
REGULATING_MODES = frozenset({"heat", "cool", "heat_cool", "auto"})
LABEL_PREFIX_MIN = 4  # a shorter token only counts as a metric word when it equals one
