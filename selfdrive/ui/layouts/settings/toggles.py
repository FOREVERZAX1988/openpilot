from cereal import log
from openpilot.common.params import Params, UnknownKeyName
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import multiple_button_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.selfdrive.ui.ui_state import ui_state

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp as toggle_item
  from openpilot.system.ui.sunnypilot.widgets.list_view import multiple_button_item_sp as multiple_button_item

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants

# Description constants
DESCRIPTIONS = {
  "OpenpilotEnabledToggle": tr_noop(
    "Use the IQ.Pilot system for adaptive cruise control and lane keep driver assistance. " +
    "Your attention is required at all times to use this feature."
  ),
  "DisengageOnAccelerator": tr_noop("When enabled, pressing the accelerator pedal will disengage IQ.Pilot."),
  "LongitudinalPersonality": tr_noop(
    "Standard is recommended. In aggressive mode, IQ.Pilot will follow lead cars closer and be more aggressive with the gas and brake. " +
    "In relaxed mode IQ.Pilot will stay further away from lead cars. On supported cars, you can cycle through these personalities with " +
    "your steering wheel distance button."
  ),
  "IsLdwEnabled": tr_noop(
    "Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line " +
    "without a turn signal activated while driving over 31 mph (50 km/h)."
  ),
  "AlwaysOnDM": tr_noop("Enable driver monitoring even when IQ.Pilot is not engaged."),
  'RecordFront': tr_noop("Upload data from the driver facing camera and help improve the driver monitoring algorithm."),
  "IsMetric": tr_noop("Display speed in km/h instead of mph."),
  "RecordAudio": tr_noop("Record and store microphone audio while driving. The audio will be included in the dashcam video in Konn3kt."),
  "TrafficAwareCruiseControl": tr_noop(
    "When enabled, IQ.Pilot uses Traffic-Aware Cruise Control (TACC). "
    "When disabled, IQ.Pilot uses end-to-end longitudinal control."
  ),
  "AlphaLongitudinalEnabled": tr_noop(
    "Enable IQ.Pilot longitudinal control on supported vehicles. " +
    "This switches longitudinal control from stock ACC to IQ.Pilot."
  ),
}


class TogglesLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = self._params.get_bool("IsReleaseBranch")
    # Keep IQ.Pilot enabled by default; the UI no longer exposes this toggle.
    self._params.put_bool("OpenpilotEnabledToggle", True)

    # param, title, desc, icon, needs_restart
    self._toggle_defs = {
      "AlphaLongitudinalEnabled": (
        lambda: tr("Longitudinal Control"),
        DESCRIPTIONS["AlphaLongitudinalEnabled"],
        "experimental_white.png",
        True,
      ),
      "ExperimentalMode": (
        lambda: tr("Long Mode"),
        DESCRIPTIONS["TrafficAwareCruiseControl"],
        "experimental_white.png",
        False,
      ),
      "DisengageOnAccelerator": (
        lambda: tr("Disengage on Accelerator Pedal"),
        DESCRIPTIONS["DisengageOnAccelerator"],
        "disengage_on_accelerator.png",
        False,
      ),
      "IsLdwEnabled": (
        lambda: tr("Enable Lane Departure Warnings"),
        DESCRIPTIONS["IsLdwEnabled"],
        "warning.png",
        False,
      ),
      "AlwaysOnDM": (
        lambda: tr("Always-On Driver Monitoring"),
        DESCRIPTIONS["AlwaysOnDM"],
        "monitoring.png",
        False,
      ),
      "RecordFront": (
        lambda: tr("Record and Upload Driver Camera"),
        DESCRIPTIONS["RecordFront"],
        "monitoring.png",
        True,
      ),
      "RecordAudio": (
        lambda: tr("Record and Upload Microphone Audio"),
        DESCRIPTIONS["RecordAudio"],
        "microphone.png",
        True,
      ),
      "IsMetric": (
        lambda: tr("Use Metric System"),
        DESCRIPTIONS["IsMetric"],
        "metric.png",
        False,
      ),
    }

    self._long_personality_setting = multiple_button_item(
      lambda: tr("Driving Personality"),
      lambda: tr(DESCRIPTIONS["LongitudinalPersonality"]),
      buttons=[lambda: tr("Aggressive"), lambda: tr("Standard"), lambda: tr("Relaxed")],
      button_width=300,
      callback=self._set_longitudinal_personality,
      selected_index=self._params.get("LongitudinalPersonality", return_default=True),
      icon="speed_limit.png"
    )

    self._toggles = {}
    self._locked_toggles = set()
    for param, (title, desc, icon, needs_restart) in self._toggle_defs.items():
      if param == "AlphaLongitudinalEnabled":
        selected_index = 0 if self._params.get_bool("AlphaLongitudinalEnabled") else 1
        toggle = multiple_button_item(
          title,
          desc,
          buttons=[lambda: tr("IQ.Pilot Longitudinal Control"), lambda: tr("Stock ACC")],
          button_width=560,
          callback=self._set_longitudinal_control_mode,
          selected_index=selected_index,
          icon=icon,
        )
      elif param == "ExperimentalMode":
        selected_index = 0 if self._params.get_bool("ExperimentalMode") else 1
        toggle = multiple_button_item(
          title,
          desc,
          buttons=[lambda: tr("IQ.Pilot"), lambda: tr("TACC")],
          button_width=300,
          callback=self._set_longitudinal_mode,
          selected_index=selected_index,
          icon=icon,
        )
      else:
        initial_state = self._params.get_bool(param)
        toggle = toggle_item(
          title,
          desc,
          initial_state,
          callback=lambda state, p=param: self._toggle_callback(state, p),
          icon=icon,
        )

      try:
        locked = self._params.get_bool(param + "Lock")
      except UnknownKeyName:
        locked = False
      toggle.action_item.set_enabled(not locked)

      # Make description callable for live translation
      additional_desc = ""
      if needs_restart and not locked:
        additional_desc = tr("Changing this setting will restart IQ.Pilot if the car is powered on.")
      toggle.set_description(lambda og_desc=toggle.description, add_desc=additional_desc: tr(og_desc) + (" " + tr(add_desc) if add_desc else ""))

      # track for engaged state updates
      if locked:
        self._locked_toggles.add(param)

      self._toggles[param] = toggle

      # insert longitudinal personality before disengage toggle
      if param == "ExperimentalMode":
        self._toggles["LongitudinalPersonality"] = self._long_personality_setting

    self._scroller = Scroller(list(self._toggles.values()), line_separator=True, spacing=0)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._long_personality_setting.action_item.set_selected_button(personality)
      ui_state.personality = personality

  def show_event(self):
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    e2e_description = tr(
      "IQ.Pilot defaults to end-to-end longitudinal control. Traffic-Aware Cruise Control is an optional mode. " +
      "IQ.Pilot features are listed below:<br>" +
      "<h4>IQ.Pilot End-to-End Longitudinal Control</h4><br>" +
      "Let the driving model control the gas and brakes. IQ.Pilot will drive as it thinks a human would, including stopping for red lights and stop signs. " +
      "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This feature is still being improved; " +
      "mistakes should be expected.<br>" +
      "<h4>New Driving Visualization</h4><br>" +
      "The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. " +
      "The IQ.Pilot logo will also be shown in the top right corner."
    )

    if ui_state.CP is not None:
      alpha_available = ui_state.CP.alphaLongitudinalAvailable and not self._is_release
      self._toggles["AlphaLongitudinalEnabled"].set_visible(alpha_available)
      if not alpha_available:
        self._toggles["AlphaLongitudinalEnabled"].action_item.set_selected_button(1)
        self._params.remove("AlphaLongitudinalEnabled")

      alpha_long_enabled = self._params.get_bool("AlphaLongitudinalEnabled")
      tacc_visible = ui_state.has_longitudinal_control and alpha_long_enabled
      self._toggles["ExperimentalMode"].set_visible(tacc_visible)

      if ui_state.has_longitudinal_control:
        if tacc_visible and self._params.get("ExperimentalMode") is None:
          # Default IQ.Pilot longitudinal to end-to-end behavior on first enable.
          self._params.put_bool("ExperimentalMode", True)
        self._toggles["ExperimentalMode"].action_item.set_enabled(tacc_visible)
        self._toggles["ExperimentalMode"].set_description(tr(DESCRIPTIONS["TrafficAwareCruiseControl"]) + "<br><br>" + e2e_description)
        self._long_personality_setting.action_item.set_enabled(True)
      else:
        # no long for now
        self._toggles["ExperimentalMode"].action_item.set_enabled(False)
        self._toggles["ExperimentalMode"].action_item.set_selected_button(0)
        self._long_personality_setting.action_item.set_enabled(False)
        self._params.remove("ExperimentalMode")

        unavailable = tr("IQ.Pilot is currently unavailable on this car since the car's stock ACC is used for longitudinal control.")

        long_desc = unavailable + " " + tr("IQ.Pilot longitudinal control may come in a future update.")
        if ui_state.CP.alphaLongitudinalAvailable:
          if self._is_release:
            long_desc = unavailable + " " + tr("IQ.Pilot longitudinal control can be tested, along with IQ.Pilot, on non-release branches.")
          else:
            long_desc = tr("Enable the IQ.Pilot longitudinal control toggle to allow IQ.Pilot.")

        self._toggles["ExperimentalMode"].set_description("<b>" + long_desc + "</b><br><br>" + tr(DESCRIPTIONS["TrafficAwareCruiseControl"]) + "<br><br>" + e2e_description)
    else:
      self._toggles["AlphaLongitudinalEnabled"].set_visible(False)
      self._toggles["ExperimentalMode"].set_visible(False)
      self._toggles["ExperimentalMode"].set_description(tr(DESCRIPTIONS["TrafficAwareCruiseControl"]) + "<br><br>" + e2e_description)

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for param in self._toggle_defs:
      if param == "AlphaLongitudinalEnabled":
        selected_index = 0 if self._params.get_bool("AlphaLongitudinalEnabled") else 1
        self._toggles[param].action_item.set_selected_button(selected_index)
      elif param == "ExperimentalMode":
        selected_index = 0 if self._params.get_bool("ExperimentalMode") else 1
        self._toggles[param].action_item.set_selected_button(selected_index)
      else:
        self._toggles[param].action_item.set_state(self._params.get_bool(param))

    # these toggles need restart, block while engaged
    for toggle_def in self._toggle_defs:
      if self._toggle_defs[toggle_def][3] and toggle_def not in self._locked_toggles:
        self._toggles[toggle_def].action_item.set_enabled(not ui_state.engaged)

  def _render(self, rect):
    self._scroller.render(rect)

  def _handle_experimental_mode_selection(self, desired_experimental: bool):
    confirmed = self._params.get_bool("ExperimentalModeConfirmed")
    if desired_experimental and not confirmed:
      def confirm_callback(result: int):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("ExperimentalMode", desired_experimental)
          self._params.put_bool("ExperimentalModeConfirmed", True)
        else:
          selected = 0 if self._params.get_bool("ExperimentalMode") else 1
          self._toggles["ExperimentalMode"].action_item.set_selected_button(selected)

      # show confirmation dialog
      content = (f"<h1>{self._toggles['ExperimentalMode'].title}</h1><br>" +
                 f"<p>{self._toggles['ExperimentalMode'].description}</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True)
      gui_app.set_modal_overlay(dlg, callback=confirm_callback)
    else:
      self._params.put_bool("ExperimentalMode", desired_experimental)

  def _toggle_callback(self, state: bool, param: str):
    if param == "AlphaLongitudinalEnabled":
      self._handle_alpha_longitudinal_toggle(state)
      return

    self._params.put_bool(param, state)
    if self._toggle_defs[param][3]:
      self._params.put_bool("OnroadCycleRequested", True)

  def _set_longitudinal_personality(self, button_index: int):
    self._params.put("LongitudinalPersonality", button_index)

  def _set_longitudinal_mode(self, button_index: int):
    # 0 = IQ.Pilot (end-to-end), 1 = TACC
    desired_experimental = button_index == 0
    if desired_experimental == self._params.get_bool("ExperimentalMode"):
      return
    self._handle_experimental_mode_selection(desired_experimental)

  def _set_longitudinal_control_mode(self, button_index: int):
    # 0 = IQ.Pilot longitudinal, 1 = Stock ACC
    desired_alpha_long = button_index == 0
    if desired_alpha_long == self._params.get_bool("AlphaLongitudinalEnabled"):
      return
    self._handle_alpha_longitudinal_toggle(desired_alpha_long)

  def _handle_alpha_longitudinal_toggle(self, state: bool):
    if state:
      def confirm_callback(result: int):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("AlphaLongitudinalEnabled", True)
          self._params.put_bool("ExperimentalMode", True)  # default to end-to-end when enabling IQ.Pilot longitudinal
          self._params.put_bool("OnroadCycleRequested", True)
        else:
          selected = 0 if self._params.get_bool("AlphaLongitudinalEnabled") else 1
          self._toggles["AlphaLongitudinalEnabled"].action_item.set_selected_button(selected)
        self._update_toggles()

      content = (f"<h1>{self._toggles['AlphaLongitudinalEnabled'].title}</h1><br>" +
                 f"<p>{self._toggles['AlphaLongitudinalEnabled'].description}</p>")
      dlg = ConfirmDialog(content, tr("Enable"), rich=True)
      gui_app.set_modal_overlay(dlg, callback=confirm_callback)
    else:
      self._params.put_bool("AlphaLongitudinalEnabled", False)
      self._params.put_bool("OnroadCycleRequested", True)
      self._update_toggles()
