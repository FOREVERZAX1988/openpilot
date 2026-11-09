"""Traffic Mode: gesture-toggled low-speed follow profile with dedicated curves.

StarPilot conditional_mode/traffic.py (gesture intent) + longitudinal/
profile_runtime.py (traffic curve resolution) port. The full StarPilot
subsystem is planner-session-bound and rides a capnp schema field
(slcState.trafficMode); this fork keeps the same core value without a
schema change:

  * gesture - a gap-adjust button press held past the very-long threshold
    toggles TrafficModeEnabled (selfdrive/car/cruise.py),
  * curves  - while enabled, the longitudinal side resolves a dedicated
    speed-interpolated follow/jerk pair and the Traffic acceleration
    profile, exactly the numbers StarPilot ships.

Curve math below is verbatim StarPilot (profile_runtime._traffic_value,
accel_profile.A_CRUISE_MAX_VALS_TRAFFIC_ALL / akima_interp) so the two
forks agree numerically.
"""
import math

TRAFFIC_BP = (0.0, 25.0)  # m/s, not mph - verbatim StarPilot

# Verbatim StarPilot accel_profile.py: the Traffic-mode cruise acceleration
# profile and its breakpoints (m/s -> m/s^2).
A_CRUISE_MAX_BP_TRAFFIC = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 40.0)
A_CRUISE_MAX_VALS_TRAFFIC_ALL = (1.10, 0.87, 0.67, 0.53, 0.44, 0.34, 0.23)

# Verbatim StarPilot profile_preferences.py bounds.
FOLLOW_MIN_SECONDS = 0.5
FOLLOW_MAX_SECONDS = 3.0
JERK_MIN = 0.25   # StarPilot JERK_MIN_PERCENT / 100
JERK_MAX = 2.0    # StarPilot JERK_MAX_PERCENT / 100

# StarPilot resolves Traffic's cruise-brake magnitude as
# |A_CRUISE_MIN| * 0.35 = 1.2 * 0.35 against a standard of 1.2, i.e. the
# traffic profile brakes at 0.35x the standard comfort deceleration. Our
# planner expresses the same idea as a comfort-brake multiplier.
TRAFFIC_COMFORT_BRAKE_FACTOR = 0.35

# Registered param defaults (params_keys.h); mirrors StarPilot's keys.
DEFAULT_TRAFFIC_FOLLOW = 0.75
DEFAULT_RELAXED_FOLLOW = 1.6
DEFAULT_JERK_PERCENT = 100.0


def interpolate_accel_profile(v_ego: float, values: tuple[float, ...] = A_CRUISE_MAX_VALS_TRAFFIC_ALL,
                              breakpoints: tuple[float, ...] = A_CRUISE_MAX_BP_TRAFFIC) -> float:
  """Verbatim StarPilot akima_interp (accel_profile.py): quintic smoothstep
  between nodes with zero slopes at the breakpoints, matching node values
  exactly and never overshooting on monotone data."""
  if len(breakpoints) != len(values) or len(breakpoints) < 2:
    raise ValueError("Acceleration profile requires matching breakpoint and value arrays")
  if v_ego <= breakpoints[0]:
    return float(values[0])
  if v_ego >= breakpoints[-1]:
    return float(values[-1])
  i = max(0, min(len(breakpoints) - 2,
                 int(next(idx for idx, bp in enumerate(breakpoints[1:], start=1) if bp >= v_ego) - 1)))
  t = (v_ego - breakpoints[i]) / float(breakpoints[i + 1] - breakpoints[i])
  t2 = t * t
  t3 = t2 * t
  t4 = t2 * t2
  return float(values[i] * (1 - 10 * t3 + 15 * t4 - 6 * t3 * t2)
               + values[i + 1] * (10 * t3 - 15 * t4 + 6 * t3 * t2))


def traffic_value(points: tuple[float, float], v_ego: float) -> float:
  """Verbatim StarPilot _traffic_value: blend low@0 m/s -> high@25 m/s."""
  ratio = min(max((v_ego - TRAFFIC_BP[0]) / (TRAFFIC_BP[1] - TRAFFIC_BP[0]), 0.0), 1.0)
  return float(points[0] + (points[1] - points[0]) * ratio)


class TrafficProfile:
  """Resolves the Traffic-mode longitudinal tuning from saved curve endpoints.

  StarPilot resolves TrafficSettings from TrafficFollow/RelaxedFollow and
  per-channel Traffic*/Relaxed* jerk percentages, validating the resolved
  follow against FOLLOW_MIN/MAX_SECONDS and rejecting non-finite values.
  Our planner consumes a single jerk channel (the MPC's jerk_factor scales
  all three cost channels together), so the acceleration channel stands in
  for the full StarPilot five-channel set.
  """

  def __init__(self, params):
    self._params = params

  def read(self) -> tuple[float, float, float, float] | None:
    """(follow_low, follow_high, jerk_low, jerk_high) or None when unreadable/invalid.

    Invalid resolved values return None (stock behaviour), matching
    StarPilot's resolve() returning None on validation failure.
    """
    try:
      follow_low = float(self._params.get_float("TrafficFollow", DEFAULT_TRAFFIC_FOLLOW))
      follow_high = float(self._params.get_float("RelaxedFollow", DEFAULT_RELAXED_FOLLOW))
      jerk_low = float(self._params.get_float("TrafficJerkAcceleration", DEFAULT_JERK_PERCENT)) / 100.0
      jerk_high = float(self._params.get_float("RelaxedJerkAcceleration", DEFAULT_JERK_PERCENT)) / 100.0
    except (TypeError, ValueError, AttributeError):
      return None
    if not all(map(math.isfinite, (follow_low, follow_high, jerk_low, jerk_high))):
      return None
    if not FOLLOW_MIN_SECONDS <= follow_low <= FOLLOW_MAX_SECONDS or not FOLLOW_MIN_SECONDS <= follow_high <= FOLLOW_MAX_SECONDS:
      return None
    if not JERK_MIN <= jerk_low <= JERK_MAX or not JERK_MIN <= jerk_high <= JERK_MAX:
      return None
    return follow_low, follow_high, jerk_low, jerk_high

  def follow(self, endpoints: tuple[float, float], v_ego: float) -> float:
    return traffic_value(endpoints, v_ego)

  def jerk(self, endpoints: tuple[float, float], v_ego: float) -> float:
    return traffic_value(endpoints, v_ego)

  def accel_cap(self, v_ego: float) -> float:
    return interpolate_accel_profile(v_ego)
