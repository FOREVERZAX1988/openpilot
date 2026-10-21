#!/usr/bin/env python3
"""Weather-conditioned driving offsets (StarPilot weather port).

StarPilot queries Open-Meteo for the current weather and derives four
offsets from it:

  * following      - seconds added to the follow time (rain, snow, fog)
  * stopped        - meters added to the stopped gap
  * acceleration   - fraction by which the requested acceleration is reduced
  * lateral        - fraction by which the lateral-acceleration ceiling is
                     reduced

The first two are additive, the last two are multiplicative. That asymmetry
matters: a rainy road should not change how much extra room you leave at a
stop by a percentage of that room, but the acceleration ceiling is a budget
and a percentage of a budget is the natural way to shrink it.

This fork keeps the classification and the offset rules but drops the network
lookup. The weather is taken from a parameter instead, which means the
feature works without a data connection and cannot be taken down by one.
The offsets themselves default to zero, so enabling the feature changes
nothing until the user actually dials a value in.

Pure logic only - no openpilot imports, safe to import on a PC host.
"""
import math

# The weather states this fork supports. StarPilot derives these from the
# WMO codes the weather service reports; here they are chosen directly.
WEATHER_STATES = ("clear", "rain", "rain_storm", "snow", "low_visibility")

# Aliases so the common spellings work too.
WEATHER_ALIASES = {
  "clear": "clear",
  "sunny": "clear",
  "rain": "rain",
  "rainstorm": "rain_storm",
  "rain_storm": "rain_storm",
  "storm": "rain_storm",
  "snow": "snow",
  "fog": "low_visibility",
  "mist": "low_visibility",
  "low_visibility": "low_visibility",
  "haze": "low_visibility",
}

# The fraction by which the lateral acceleration is scaled. Applied to the
# comfort ceiling, so 0.2 means "20 percent less lateral acceleration".
def clamp_fraction(value) -> float:
  try:
    value = float(value)
  except (TypeError, ValueError):
    return 0.0
  if not math.isfinite(value):
    return 0.0
  return float(min(max(value, 0.0), 1.0))


def clamp_seconds(value) -> float:
  try:
    value = float(value)
  except (TypeError, ValueError):
    return 0.0
  if not math.isfinite(value):
    return 0.0
  return float(min(max(value, 0.0), 3.0))


def clamp_meters(value) -> float:
  try:
    value = float(value)
  except (TypeError, ValueError):
    return 0.0
  if not math.isfinite(value):
    return 0.0
  return float(min(max(value, 0.0), 20.0))


def normalize_weather_state(state) -> str:
  """Map a user-supplied weather name to a known state. Unknown -> clear."""
  if not isinstance(state, str):
    return "clear"
  key = state.strip().lower().replace(" ", "").replace("-", "_")
  if key in WEATHER_ALIASES:
    return WEATHER_ALIASES[key]
  return "clear"


class WeatherOffsets:
  """The four offsets for the current weather.

  The values are stored separately from the state so the caller can update
  them without re-resolving the state, and so a weather change is visible
  without recomputing anything.
  """

  def __init__(self, state: str = "clear", *, following: float = 0.0, stopped: float = 0.0,
               acceleration: float = 0.0, lateral: float = 0.0):
    self.state = normalize_weather_state(state)
    self.increase_following_distance = clamp_seconds(following)
    self.increase_stopped_distance = clamp_meters(stopped)
    self.reduce_acceleration = clamp_fraction(acceleration)
    self.reduce_lateral_acceleration = clamp_fraction(lateral)

  @property
  def is_adverse(self) -> bool:
    """True when the weather is anything other than clear."""
    return self.state != "clear"

  def apply_following(self, t_follow: float) -> float:
    """Add the weather margin to a follow time."""
    return float(t_follow) + self.increase_following_distance

  def apply_stopped_distance(self, distance: float) -> float:
    """Add the weather margin to a stopped gap."""
    return float(distance) + self.increase_stopped_distance

  def apply_acceleration(self, max_accel: float) -> float:
    """Scale an acceleration ceiling down by the weather fraction."""
    return float(max_accel) * (1.0 - self.reduce_acceleration)

  def apply_lateral_acceleration(self, lat_accel: float) -> float:
    """Scale a lateral-acceleration ceiling down by the weather fraction."""
    return float(lat_accel) * (1.0 - self.reduce_lateral_acceleration)

  def as_dict(self) -> dict:
    return {
      "state": self.state,
      "increase_following_distance": self.increase_following_distance,
      "increase_stopped_distance": self.increase_stopped_distance,
      "reduce_acceleration": self.reduce_acceleration,
      "reduce_lateral_acceleration": self.reduce_lateral_acceleration,
    }
