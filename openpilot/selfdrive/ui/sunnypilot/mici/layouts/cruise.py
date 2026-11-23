"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.selfdrive.ui.sunnypilot.mici.layouts.alpha_longitudinal import AlphaLongitudinalTogglesMici
from openpilot.selfdrive.ui.sunnypilot.mici.widgets.button import (
  BigButtonSP,
  BigMultiParamToggleSP,
  BigParamControlSP,
  BigParamOption,
  speed_unit,
)
from openpilot.selfdrive.ui.mici.widgets.button import BigMultiToggle
from openpilot.selfdrive.ui.sunnypilot.lib.following_profile_store import (
  PRESET_ORDER,
  PROFILE_PARAM_KEY,
  serialize_selection,
  selection_from_raw,
)
from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.sunnypilot.selfdrive.car.intelligent_cruise_button_management.helpers import icbm_moves_speed_limits
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Policy
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.source_auto import AUTO, car_shows_limit
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.tiered_offset import (
  TIER_KEY_SUFFIXES,
  tier_label,
)

SL_MODE_LABELS = [tr("off"), tr("info"), tr("warn"), tr("assist")]
SL_SOURCE_LABELS = {AUTO: tr("auto"), Policy.car_state_only: tr("car"), Policy.map_data_only: tr("map")}
SL_MODE_OFF = 0
SL_MODE_WARN = 2
SL_MODE_ASSIST = 3
SL_OFFSET_FIXED = 1
SL_OFFSET_PERCENT = 2
SL_OFFSET_TIERED = 3
SL_CONFIRM_LABELS = [tr("never"), tr("lower"), tr("higher"), tr("both")]
ACC_LONG_PRESS_MAP = {1: 1, 2: 5, 3: 10}

# Following Profile preset labels, in PRESET_ORDER order (following_profile_store).
FOLLOWING_PRESET_LABELS = [tr("close"), tr("medium"), tr("far")]
FOLLOWING_PERSONALITY_LABELS = {
  "aggressive": "aggressive personality",
  "standard": "standard personality",
  "relaxed": "relaxed personality",
}
FOLLOWING_PROFILE_DESCRIPTION = tr("Replaces the single following distance per personality with a speed-dependent profile.\n" +
                                   "The follow time is interpolated over speed, so the gap can be shorter in town and longer on the highway.")

# Longitudinal MPC Tuning: (title, param, min, max, step, digits), values stored scaled x100.
MPC_TUNING_PARAMS = [
  (tr("comfort brake"), "LongitudinalMpcTuningComfortBrake", 150, 450, 5, 2),
  (tr("stop distance"), "LongitudinalMpcTuningStopDistance", 200, 1200, 50, 1),
  (tr("follow time - relaxed"), "LongitudinalMpcTuningTFollowRelaxed", 100, 250, 5, 2),
  (tr("follow time - standard"), "LongitudinalMpcTuningTFollowStandard", 100, 220, 5, 2),
  (tr("follow time - aggressive"), "LongitudinalMpcTuningTFollowAggressive", 80, 180, 5, 2),
  (tr("distance cost"), "LongitudinalMpcTuningXEgoObstacleCost", 50, 600, 25, 2),
  (tr("jerk cost"), "LongitudinalMpcTuningJEgoCost", 100, 1500, 50, 2),
  (tr("acceleration change cost"), "LongitudinalMpcTuningAChangeCost", 5000, 60000, 500, 0),
  (tr("danger zone cost"), "LongitudinalMpcTuningDangerZoneCost", 0, 50000, 500, 0),
  (tr("lead danger factor"), "LongitudinalMpcTuningLeadDangerFactor", 25, 150, 5, 2),
]
# Three-channel jerk scaling per personality. 1.00 means "unchanged".
MPC_TUNING_JERK_PARAMS = [
  (tr(f"{channel} - {personality}"), f"LongitudinalMpcTuning{personality}{key}", 25, 200, 5, 2)
  for personality in ("Aggressive", "Standard", "Relaxed")
  for key, channel in (("JerkAccel", tr("accel smoothness")), ("JerkSpeed", tr("speed smoothness")),
                       ("DangerBias", tr("safety gap bias")), ("JerkDanger", tr("danger smoothness")))
]
# Defaults in the scaled x100 domain (longitudinal_mpc_tuning.py _reset_defaults).
MPC_TUNING_DEFAULTS = {
  "LongitudinalMpcTuningComfortBrake": 250,
  "LongitudinalMpcTuningStopDistance": 600,
  "LongitudinalMpcTuningTFollowRelaxed": 175,
  "LongitudinalMpcTuningTFollowStandard": 145,
  "LongitudinalMpcTuningTFollowAggressive": 125,
  "LongitudinalMpcTuningXEgoObstacleCost": 300,
  "LongitudinalMpcTuningJEgoCost": 500,
  "LongitudinalMpcTuningAChangeCost": 20000,
  "LongitudinalMpcTuningDangerZoneCost": 10000,
  "LongitudinalMpcTuningLeadDangerFactor": 75,
}


def _mpc_label(digits: int):
  return lambda v: f"{v / 100.0:.{digits}f}"


class FollowingProfilePickerMici(BigMultiToggle):
  """One preset picker per driving personality.

  The presets live in the LongitudinalFollowingProfile JSON document, so unlike
  BigMultiParamToggleSP the click handler re-serializes the whole selection.
  """

  def __init__(self, personality: str, title: str, description: str):
    self._params = Params()
    self._personality = personality
    super().__init__(title, FOLLOWING_PRESET_LABELS, select_callback=self._on_select, description=description)
    self._selection = selection_from_raw(self._params.get(PROFILE_PARAM_KEY))
    self.set_value(FOLLOWING_PRESET_LABELS[PRESET_ORDER.index(self._selection[personality])])

  def _on_select(self, label: str):
    preset = PRESET_ORDER[FOLLOWING_PRESET_LABELS.index(label)]
    if self._selection.get(self._personality) == preset:
      return
    self._selection[self._personality] = preset
    self._params.put(PROFILE_PARAM_KEY, serialize_selection(self._selection))

  def refresh(self):
    self._selection = selection_from_raw(self._params.get(PROFILE_PARAM_KEY))
    self.set_value(FOLLOWING_PRESET_LABELS[PRESET_ORDER.index(self._selection[self._personality])])


def _offset_unit():
  t = int(ui_state.params.get("SpeedLimitOffsetType", return_default=True))
  if t == 2:
    return "%"
  if t == 1:
    return speed_unit()
  return ""


def _offset_label(value):
  unit = _offset_unit()
  return f"{value}{unit}" if unit else tr("none")


class CruiseLayoutMici(NavScroller):
  """Cruise settings: alpha longitudinal, following profile, ICBM, Set Speed Assist, SCC, speed limit
  assist, conditional chill exit, acceleration boost, custom ACC increments, and MPC tuning.

  State gating pattern:
    - _update_state runs every frame, reads params and enables/disables widgets
    - _prev_* fields track state transitions (None → first frame, True → False = cleanup)
    - ICBM's toggle is enabled wherever the car supports it without openpilot longitudinal
      control (icbm_applicable); with longitudinal control it is locked and cleared
  """

  def __init__(self):
    super().__init__()

    self._prev_sla_available: bool | None = None
    self._prev_icbm_available: bool | None = None

    self._alpha_long = AlphaLongitudinalTogglesMici()
    # Following Profile: master switch plus a preset picker per personality.
    self._following_toggle = BigParamControlSP(tr("custom following profiles"), "LongitudinalFollowingProfileEnabled",
                                               description=FOLLOWING_PROFILE_DESCRIPTION)
    self._following_pickers = {
      personality: FollowingProfilePickerMici(personality, tr(FOLLOWING_PERSONALITY_LABELS[personality]),
                                              description=tr("Preset used for this driving personality: close follows nearest, far leaves the most space."))
      for personality in ("aggressive", "standard", "relaxed")
    }
    for picker in self._following_pickers.values():
      picker.set_visible(lambda: self._following_toggle._checked)
    self._icbm_toggle = BigParamControlSP(tr("cruise button management"), "IntelligentCruiseButtonManagement",
                                          description=tr("Manages the car's built-in cruise buttons by emulating presses for limited longitudinal control."))
    self._scc_v_toggle = BigParamControlSP(tr("slow for curves: vision"), "SmartCruiseControlVision",
                                           description=tr("Slows for curves the camera sees, then resumes your set speed.\n" +
                                                          "Works alone or with slow for curves: map."))
    self._scc_m_toggle = BigParamControlSP(tr("slow for curves: map"), "SmartCruiseControlMap",
                                           description=tr("Slows for curves in map data, then resumes your set speed.\n" +
                                                          "Download maps in sunnylink first."))
    # stored value is the index into curve_speed_profile.SCALES
    self._curve_speed = BigMultiParamToggleSP(tr("curve speed"), "CurveSpeedProfile", [tr("gentle"), tr("normal"), tr("sporty")],
                                              description=tr("How fast slow for curves takes turns.\n" +
                                                             "Gentle slows more. Sporty slows less."))
    # Conditional chill exit: while legacy chill is on, selfdrived flips ExperimentalMode from
    # driving context. The sub-toggles map one-to-one onto the CEM conditions.
    self._cem_toggle = BigParamControlSP(tr("conditional chill exit"), "ConditionalExperimental",
                                         description=tr("While chill mode is on, temporarily switch to experimental mode " +
                                                        "on demanding curves, slow leads and low-speed turns.\n" +
                                                        "A manual switch keeps priority for a minute."))
    self._cem_curves_toggle = BigParamControlSP(tr("curves"), "CECurves", depends_on=lambda: self._cem_toggle._checked,
                                                description=tr("Experimental mode follows lateral acceleration while cornering."))
    self._cem_curves_lead_toggle = BigParamControlSP(tr("curves while following"), "CECurvesLead", depends_on=lambda: self._cem_toggle._checked,
                                                     description=tr("Allows the curve trigger while following a lead car."))
    self._cem_lead_toggle = BigParamControlSP(tr("slow leads"), "CELead", depends_on=lambda: self._cem_toggle._checked,
                                              description=tr("Experimental mode engages when closing on a slower lead."))

    self._accel_boost_toggle = BigParamControlSP(tr("acceleration boost"), "AccelBoostSP",
                                                 description=tr("Adds a small push on top of the planned acceleration, stronger in aggressive " +
                                                                "and gentler in relaxed.\n" +
                                                                "Eases off in curves and when slowing or stopping. Never goes past your set speed."))

    self._custom_acc_btn = BigButtonSP(tr("custom increments"))
    self._speed_limit_btn = BigButtonSP(tr("speed limit"))
    self._mpc_tuning_btn = BigButtonSP(tr("longitudinal mpc tuning"))

    for btn in [self._custom_acc_btn, self._speed_limit_btn, self._mpc_tuning_btn]:
      btn.set_subtitle_font_size(24)

    self._scroller.add_widgets([
      *self._alpha_long.items,
      self._following_toggle, *self._following_pickers.values(),
      self._icbm_toggle,
      self._scc_v_toggle, self._scc_m_toggle, self._curve_speed,
      self._speed_limit_btn, self._custom_acc_btn,
      self._cem_toggle, self._cem_curves_toggle, self._cem_curves_lead_toggle, self._cem_lead_toggle,
      self._accel_boost_toggle,
      self._mpc_tuning_btn,
    ])

    self._custom_acc_toggle = BigParamControlSP(tr("enable custom increments"), "CustomAccIncrementsEnabled",
                                                description=tr("Set how far a short press and a long press of + or - move your set speed."))

    def _speed_label(v):
      return f"{v} {speed_unit()}"
    self._acc_short = BigParamOption(tr("short press"), "CustomAccShortPressIncrement",
                                     min_value=1, max_value=10, label_callback=_speed_label, picker_unit=speed_unit,
                                     description=tr("How far one tap of + or - moves your set speed."))
    self._acc_long = BigParamOption(tr("long press"), "CustomAccLongPressIncrement",
                                    min_value=1, max_value=3, value_map=ACC_LONG_PRESS_MAP,
                                    label_callback=_speed_label, picker_unit=speed_unit,
                                    description=tr("How far holding + or - moves your set speed at each step."))
    self._acc_view = self._custom_acc_btn.link_sub_panel([self._custom_acc_toggle, self._acc_short, self._acc_long])

    self._sl_mode = BigMultiParamToggleSP(tr("speed limit mode"), "SpeedLimitMode", SL_MODE_LABELS, off_index=0,
                                          description=tr("Assist: when the limit changes, press - or + to set your speed to match.\n" +
                                                         "Info and warn show the sign on a comma 3X only."))
    self._sl_mode.set_blocked_options(lambda: set() if ui_state.icbm_turn_on_allowed("SpeedLimitMode", True) else {SL_MODE_ASSIST})
    self._sl_source = BigMultiParamToggleSP(tr("source"), "SpeedLimitPolicy", list(SL_SOURCE_LABELS.values()), values=list(SL_SOURCE_LABELS),
                                            description=tr("Auto follows the limit your car shows, and the map where it shows none.\n" +
                                                           "The map also slows you before a lower limit ahead.\n" +
                                                           "Car or map uses only that one."))
    # cars that report no limit always use the map
    self._sl_source.set_visible(lambda: car_shows_limit(ui_state.CP, ui_state.CP_SP))
    self._sl_offset_type = BigMultiParamToggleSP(tr("offset type"), "SpeedLimitOffsetType",
                                                 [tr("none"), tr("fixed"), "%", tr("tiered")], off_index=0,
                                                 description=tr("Adds an offset to the speed limit.\n" +
                                                                "Fixed adds a set amount of speed. % adds a percentage of the limit.\n" +
                                                                "Tiered adds a different offset for each speed limit range."))
    self._sl_offset_value = BigParamOption(tr("offset value"), "SpeedLimitValueOffset",
                                           min_value=-30, max_value=30, label_callback=_offset_label, picker_unit=_offset_unit,
                                           description=tr("The amount added to the speed limit. Negative values go below it."))
    self._sl_confirm = BigMultiParamToggleSP(tr("confirm limit changes"), "SpeedLimitConfirmOnChange", SL_CONFIRM_LABELS, off_index=0,
                                             description=tr("Asks before taking a new speed limit. Adds to the low-speed confirmation, never replaces it."))
    self._sl_tiered_btn = BigButtonSP(tr("tiered offsets"))
    self._sl_tiered_btn.set_subtitle_font_size(24)

    def _tier_title(idx: int):
      return tr("limit") + f" {tier_label(idx, ui_state.is_metric)}"

    self._sl_tiered_options = [
      BigParamOption(_tier_title(idx), key, min_value=-30, max_value=30,
                     label_callback=lambda v: f"{v} {speed_unit()}", picker_unit=speed_unit,
                     description=tr("The offset applied to the speed limit in this range."))
      for idx, key in enumerate(TIER_KEY_SUFFIXES)
    ]
    self._sl_tiered_view = self._sl_tiered_btn.link_sub_panel(self._sl_tiered_options)
    self._sl_view = self._speed_limit_btn.link_sub_panel([self._sl_mode, self._sl_source, self._sl_offset_type,
                                                          self._sl_offset_value, self._sl_confirm, self._sl_tiered_btn])

    # Longitudinal MPC tuning: values are stored scaled x100, like the TICI panel.
    self._mpc_options = [
      BigParamOption(title, param, min_value=mn, max_value=mx, value_change_step=step,
                     label_callback=_mpc_label(digits), picker_label_callback=lambda v, d=digits: f"{v / 100.0:.{d}f}")
      for title, param, mn, mx, step, digits in MPC_TUNING_PARAMS + MPC_TUNING_JERK_PARAMS
    ]
    self._mpc_reset_btn = BigButtonSP(tr("reset to defaults"))

    def _mpc_reset():
      params = ui_state.params
      for option in self._mpc_options:
        default = MPC_TUNING_DEFAULTS.get(option._param, 100)
        params.put(option._param, default / 100.0)
        option.refresh()

    self._mpc_reset_btn.set_click_callback(_mpc_reset)
    self._mpc_view = self._mpc_tuning_btn.link_sub_panel([*self._mpc_options, self._mpc_reset_btn])

  def show_event(self):
    super().show_event()
    self._alpha_long.refresh()
    self._following_toggle.refresh()
    for picker in self._following_pickers.values():
      picker.refresh()

  def _update_state(self):
    super()._update_state()
    self._alpha_long.update_state()

    self._scc_v_toggle.refresh()
    self._scc_m_toggle.refresh()
    self._curve_speed.refresh()
    self._following_toggle.refresh()
    self._icbm_toggle.refresh()
    for toggle in (self._cem_toggle, self._cem_curves_toggle, self._cem_curves_lead_toggle, self._cem_lead_toggle,
                   self._accel_boost_toggle):
      toggle.refresh()

    cp_ready = ui_state.CP is not None and ui_state.CP_SP is not None
    has_long = cp_ready and ui_state.has_longitudinal_control
    has_icbm = cp_ready and ui_state.has_icbm

    # Following profile needs longitudinal control
    self._following_toggle.set_enabled(has_long)
    for picker in self._following_pickers.values():
      picker.set_enabled(has_long)

    # ICBM: usable only where the car supports it and openpilot long is not the active control
    icbm_available = cp_ready and ui_state.CP_SP.intelligentCruiseButtonManagementAvailable and not has_long
    if not icbm_available and self._prev_icbm_available is not False:
      ui_state.params.remove("IntelligentCruiseButtonManagement")
    self._prev_icbm_available = icbm_available
    self._icbm_toggle.set_enabled(icbm_available and ui_state.is_offroad())

    self._accel_boost_toggle.set_enabled(cp_ready)

    for toggle in (self._scc_v_toggle, self._scc_m_toggle):
      toggle.set_superseded(not (has_long or has_icbm))
    # nothing reads it with both curve features off
    self._curve_speed.set_superseded(not (has_long or has_icbm) or not (self._scc_v_toggle._checked or self._scc_m_toggle._checked))
    # has_long and has_icbm are False until CP is ready, so CP is not read before then
    custom_acc_available = (has_long and not ui_state.CP.pcmCruise) or has_icbm
    self._custom_acc_toggle.set_superseded(not custom_acc_available)
    self._custom_acc_btn.set_enabled(custom_acc_available)

    # engaged with ICBM off, only turning these off is allowed (ui_state.icbm_turn_on_allowed)
    for toggle in (self._scc_v_toggle, self._scc_m_toggle):
      toggle.set_enabled(ui_state.icbm_turn_on_allowed(toggle.param, not toggle._checked))

    # Custom ACC button subtitle
    acc_on = ui_state.params.get_bool("CustomAccIncrementsEnabled")
    if not acc_on:
      self._custom_acc_btn.set_disabled()
    else:
      unit = speed_unit()
      short_val = ui_state.params.get("CustomAccShortPressIncrement", return_default=True) or 1
      long_raw = ui_state.params.get("CustomAccLongPressIncrement", return_default=True) or 1
      long_val = ACC_LONG_PRESS_MAP.get(long_raw, long_raw)
      self._custom_acc_btn.set_badges([(f"{short_val}{unit}", "on"), (f"{long_val}{unit}", "on")])

    # Speed limit button subtitle
    sl_mode_idx = ui_state.params.get("SpeedLimitMode", return_default=True) or 0
    sl_mode = SL_MODE_LABELS[min(sl_mode_idx, len(SL_MODE_LABELS) - 1)]
    offset_type = ui_state.params.get("SpeedLimitOffsetType", return_default=True)
    if sl_mode_idx == SL_MODE_OFF:
      self._speed_limit_btn.set_disabled()
    else:
      sl_source = SL_SOURCE_LABELS.get(ui_state.params.get("SpeedLimitPolicy", return_default=True), SL_SOURCE_LABELS[AUTO])
      sl_offset_val = ui_state.params.get("SpeedLimitValueOffset", return_default=True) or 0
      unit = "%" if offset_type == 2 else (speed_unit() if offset_type == 1 else "")
      icbm = icbm_moves_speed_limits(has_long, has_icbm, sl_mode_idx)
      badges = [(sl_mode, "on"), (tr("icbm"), "on" if icbm else "off")]
      if car_shows_limit(ui_state.CP, ui_state.CP_SP):
        badges.append((sl_source, "on"))
      if offset_type == SL_OFFSET_TIERED:
        badges.append((tr("tiered"), "on"))
      elif unit:
        sign = "+" if sl_offset_val > 0 else ""
        badges.append((f"{sign}{sl_offset_val}{unit}", "on"))
      self._speed_limit_btn.set_badges(badges)

    self._update_custom_acc_state()
    self._update_speed_limit_state(cp_ready, has_long, has_icbm, offset_type)

  def _update_custom_acc_state(self):
    if not gui_app.widget_in_stack(self._acc_view):
      return
    self._custom_acc_toggle.set_enabled(ui_state.icbm_turn_on_allowed("CustomAccIncrementsEnabled", not self._custom_acc_toggle._checked))
    # Lambda: short/long respond same-frame when toggle is tapped (see button.py docstring)
    self._acc_short.set_enabled(lambda: self._custom_acc_btn.enabled and self._custom_acc_toggle._checked)
    self._acc_long.set_enabled(lambda: self._custom_acc_btn.enabled and self._custom_acc_toggle._checked)

  def _update_speed_limit_state(self, cp_ready: bool, has_long: bool, has_icbm: bool, offset_type: int):
    # SLA availability gating (must always run)
    sla_available = False
    if cp_ready:
      brand = ui_state.CP.brand
      sla_disallow_in_release = brand == "tesla" and ui_state.is_sp_release
      sla_always_disallow = brand == "rivian"
      sla_available = (has_long or has_icbm) and not sla_disallow_in_release and not sla_always_disallow

    # Downgrade unavailable assist mode to warning once per transition.
    if not sla_available and self._prev_sla_available is not False:
      sl_mode_idx = ui_state.params.get("SpeedLimitMode", return_default=True) or 0
      if sl_mode_idx == SL_MODE_ASSIST:
        ui_state.params.put("SpeedLimitMode", SL_MODE_WARN)
    self._prev_sla_available = sla_available

    if not gui_app.widget_in_stack(self._sl_view):
      return
    self._sl_mode.set_enabled(True)
    # nothing reads these with the mode off
    sl_on = self._sl_mode.value != SL_MODE_LABELS[SL_MODE_OFF]
    self._sl_source.set_superseded(not sl_on)
    self._sl_offset_type.set_superseded(not sl_on)
    self._sl_offset_value.set_enabled(sl_on and offset_type in (SL_OFFSET_FIXED, SL_OFFSET_PERCENT))  # 0 = off/none, 3 = tiered
    self._sl_confirm.set_superseded(not sl_on)
    self._sl_tiered_btn.set_enabled(sl_on and offset_type == SL_OFFSET_TIERED)
    if not gui_app.widget_in_stack(self._mpc_view):
      return
    for option in self._mpc_options:
      option.set_enabled(has_long)
