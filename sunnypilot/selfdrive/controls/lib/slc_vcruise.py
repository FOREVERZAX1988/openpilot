#!/usr/bin/env python3
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit_controller import SpeedLimitController
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode as SpeedLimitMode

CRUISING_SPEED = 7  # m/s - Minimum speed to consider "cruising"


class SLCVCruise:
  """
  VCruise wrapper for Speed Limit Controller.
  Adjusts cruise speed based on detected speed limits.
  """

  def __init__(self):
    """Initialize SLC VCruise wrapper."""
    self.params = Params()

    self.slc = SpeedLimitController(self.params)

    # Exposed SLC state (for UI/logging)
    self.slc_offset = 0
    self.slc_target = 0
    self.slc_source = "None"
    self.slc_unconfirmed = 0
    self.slc_overridden_speed = 0
    self.slc_active_target = 0
    self.slc_active_source = "None"

  def _get_slc_params(self):
    """
    Load SLC parameters from Params.

    Returns:
      Dictionary of SLC configuration parameters
    """
    def get_param_bool(key, default=False):
      value = self.params.get_bool(key)
      return value if value is not None else default

    def get_param_float(key, default=0.0):
      value = self.params.get(key)
      if value is None:
        return default
      if isinstance(value, bytes):
        try:
          return float(value.decode('utf-8'))
        except (ValueError, AttributeError):
          return default
      return float(value)

    def get_param_str(key, default=""):
      value = self.params.get(key)
      if value is None:
        return default
      if isinstance(value, bytes):
        return value.decode('utf-8')
      return str(value)

    # Parse priority mode from SLCPriority parameter (0=Dashboard First, 1=Mapbox First, 2=Map First, 3=Highest, 4=Lowest)
    priority_mode = int(get_param_str("SLCPriority", "0"))

    # Map priority mode to settings
    if priority_mode == 0:  # Dashboard First
      priority1, priority2, priority3 = "Dashboard", "Mapbox", "Map Data"
      priority_highest, priority_lowest = False, False
    elif priority_mode == 1:  # Mapbox First
      priority1, priority2, priority3 = "Mapbox", "Dashboard", "Map Data"
      priority_highest, priority_lowest = False, False
    elif priority_mode == 2:  # Map Data First
      priority1, priority2, priority3 = "Map Data", "Mapbox", "Dashboard"
      priority_highest, priority_lowest = False, False
    elif priority_mode == 3:  # Highest
      priority1, priority2, priority3 = "Dashboard", "Mapbox", "Map Data"
      priority_highest, priority_lowest = True, False
    else:  # Lowest (4)
      priority1, priority2, priority3 = "Dashboard", "Mapbox", "Map Data"
      priority_highest, priority_lowest = False, True

    # Parse override method from SLCOverrideMethod parameter (0=Manual Gas, 1=Set Speed)
    override_method = int(get_param_str("SLCOverrideMethod", "0"))
    override_manual = (override_method == 0)
    override_set_speed = (override_method == 1)

    speed_limit_mode = int(get_param_str("SpeedLimitMode", str(int(SpeedLimitMode.information))))
    speed_limit_controller = get_param_bool("SpeedLimitController")
    show_speed_limits = get_param_bool("ShowSpeedLimits")

    # Compatibility bridge:
    # Prefer the newer SpeedLimitMode state when present so this legacy
    # controller integrates with current IQ.Pilot UI/state.
    if speed_limit_mode == int(SpeedLimitMode.off):
      speed_limit_controller = False
      show_speed_limits = False
    elif speed_limit_mode == int(SpeedLimitMode.assist):
      speed_limit_controller = True
      show_speed_limits = False
    else:
      speed_limit_controller = False
      show_speed_limits = True

    return {
      # Main toggles
      "speed_limit_controller": speed_limit_controller,
      "show_speed_limits": show_speed_limits,

      # Priority settings
      "speed_limit_priority_highest": priority_highest,
      "speed_limit_priority_lowest": priority_lowest,
      "speed_limit_priority1": priority1,
      "speed_limit_priority2": priority2,
      "speed_limit_priority3": priority3,

      # Confirmation settings
      "speed_limit_confirmation_higher": get_param_bool("SpeedLimitConfirmationHigher"),
      "speed_limit_confirmation_lower": get_param_bool("SpeedLimitConfirmationLower"),

      # Lookahead settings (in seconds)
      "map_speed_lookahead_higher": get_param_float("MapSpeedLookaheadHigher", 5.0),
      "map_speed_lookahead_lower": get_param_float("MapSpeedLookaheadLower", 5.0),

      # Fallback settings
      "slc_fallback_experimental_mode": get_param_bool("SLCFallbackExperimentalMode"),
      "slc_fallback_set_speed": get_param_bool("SLCFallbackSetSpeed"),
      "slc_fallback_previous_speed_limit": get_param_bool("SLCFallbackPreviousSpeedLimit"),

      # Override settings
      "speed_limit_controller_override_manual": override_manual,
      "speed_limit_controller_override_set_speed": override_set_speed,

      # Mapbox settings
      "slc_mapbox_filler": get_param_bool("SLCMapboxFiller"),

      # Unit system
      "is_metric": get_param_bool("IsMetric"),
    }

  def update(self, long_control_active, now, time_validated, v_cruise, v_ego, sm):
    """
    Update cruise speed based on SLC.

    Args:
      long_control_active: Boolean indicating if longitudinal control is active
      now: Current datetime
      time_validated: Boolean indicating if time is validated
      v_cruise: Current cruise speed setpoint in m/s
      v_ego: Current vehicle speed in m/s
      sm: SubMaster instance with car/selfdriveState data

    Returns:
      Modified cruise speed in m/s
    """
    slc_params = self._get_slc_params()
    is_metric = slc_params["is_metric"]

    # Get cluster speeds for difference calculation
    v_cruise_cluster = max(sm["carState"].vCruiseCluster * CV.KPH_TO_MS, v_cruise)
    v_cruise_diff = v_cruise_cluster - v_cruise

    v_ego_cluster = max(sm["carState"].vEgoCluster, v_ego)
    v_ego_diff = v_ego_cluster - v_ego

    # Get dashboard speed limit from carStateSP if available
    if sm.alive.get("carStateSP", False) and hasattr(sm["carStateSP"], "speedLimit"):
      dashboard_speed_limit = sm["carStateSP"].speedLimit
    else:
      dashboard_speed_limit = 0

    # Update SLC
    if slc_params["speed_limit_controller"]:
      self.slc.update_limits(dashboard_speed_limit, now, time_validated, v_cruise, v_ego, sm, slc_params)
      self.slc.update_override(v_cruise, v_cruise_diff, v_ego, v_ego_diff, sm, slc_params, is_metric)

      self.slc_offset = self.slc.get_offset(is_metric)
      self.slc_target = self.slc.target
      self.slc_source = self.slc.source
      self.slc_active_target = self.slc.active_target
      self.slc_active_source = self.slc.active_source
      self.slc_unconfirmed = self.slc.unconfirmed_speed_limit
      self.slc_overridden_speed = self.slc.overridden_speed

    elif slc_params["show_speed_limits"]:
      # Show speed limits without controlling cruise speed
      self.slc.update_limits(dashboard_speed_limit, now, time_validated, v_cruise, v_ego, sm, slc_params)

      self.slc_offset = 0
      self.slc_target = self.slc.target
      self.slc_source = self.slc.source
      self.slc_active_target = self.slc.active_target
      self.slc_active_source = self.slc.active_source
      self.slc_unconfirmed = self.slc.unconfirmed_speed_limit
      self.slc_overridden_speed = 0

    else:
      # SLC disabled
      self.slc_offset = 0
      self.slc_target = 0
      self.slc_source = "None"
      self.slc_active_target = 0
      self.slc_active_source = "None"
      self.slc_unconfirmed = 0
      self.slc_overridden_speed = 0

    # Apply SLC to cruise speed if enabled
    if slc_params["speed_limit_controller"] and long_control_active:
      # Calculate SLC target with offset
      slc_cruise_target = max(self.slc_overridden_speed, self.slc_target + self.slc_offset) - v_ego_diff

      # Only apply SLC if target is above minimum cruising speed
      if slc_cruise_target >= CRUISING_SPEED:
        v_cruise = min(v_cruise, slc_cruise_target)

    return v_cruise
