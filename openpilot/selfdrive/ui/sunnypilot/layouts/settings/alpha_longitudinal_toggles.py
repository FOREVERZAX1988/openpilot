"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

The alpha switch and the modes that run on openpilot longitudinal control, at the top of the tizi
Cruise panel. Toggles and Developer drop their copies of the first two (TogglesLayoutSP,
DeveloperLayoutSP) so each switch appears once.
"""
from openpilot.selfdrive.ui.layouts.settings.developer import DESCRIPTIONS as DEVELOPER_DESCRIPTIONS
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog

# upstream's Toggles text (layouts/settings/toggles.py) with our name, shown again in the confirm dialog
EXPERIMENTAL_MODE_DESCRIPTION = tr_noop(
  "sunnypilot defaults to driving in chill mode. Experimental mode enables alpha-level features that aren't ready for chill mode. " +
  "Experimental features are listed below:<br>" +
  "<h4>End-to-End Longitudinal Control</h4><br>" +
  "Let the driving model control the gas and brakes. zoompilot will drive as it thinks a human would, including stopping for red lights and stop signs. " +
  "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; " +
  "mistakes should be expected.<br>" +
  "<h4>New Driving Visualization</h4><br>" +
  "The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. " +
  "The Experimental mode logo will also be shown in the top right corner."
)


class AlphaLongitudinalToggles:
  """Not a panel: CruiseLayout lists `items` in its own scroller and drives the two hooks."""
  def __init__(self):
    self._alpha_long_toggle = toggle_item_sp(
      title=lambda: tr("Alpha Longitudinal"),
      description=lambda: tr(DEVELOPER_DESCRIPTIONS["alpha_longitudinal"]),
      callback=self._on_alpha_long,
      enabled=ui_state.is_offroad,
      sync_param="AlphaLongitudinalEnabled")

    self._experimental_toggle = toggle_item_sp(
      title=lambda: tr("Experimental Mode"),
      description=lambda: tr(EXPERIMENTAL_MODE_DESCRIPTION),
      callback=self._on_experimental_mode,
      # the write belongs to the callback (it may need the risk dialog first), so the
      # switch only mirrors the key: a mode set from the web panel or the companion app
      # shows here without waiting for the next offroad/engaged transition
      sync_param="ExperimentalMode")

    self._set_speed_toggle = toggle_item_sp(
      title=lambda: tr("Experimental Mode Speed Assist"),
      description=lambda: tr("In Experimental Mode, gently raise speed toward the set speed when nothing calls for slowing down."),
      param="ExperimentalModeSetSpeed")

    self._lead_gap_toggle = toggle_item_sp(
      title=lambda: tr("Experimental Mode Lead Follow Assist"),
      description=lambda: tr("Closes the gap to your driving personality's following distance behind a steady car. " +
                             "Never closer than chill mode."),
      param="ExperimentalModeLeadGap")

    # Which situations may hand speed control to the model under DEC. All on by
    # default; a switch that is off can only stop a hand-over, never cause one.
    self._dec_trigger_specs = (
      ("DynamicExperimentalTriggerCurve", tr_noop("DEC: Curves"),
       tr_noop("Let a curve ahead hand speed control to the model.")),
      ("DynamicExperimentalTriggerLead", tr_noop("DEC: Slower Lead"),
       tr_noop("Let a slower or stopped car ahead hand speed control to the model.")),
      ("DynamicExperimentalTriggerSignal", tr_noop("DEC: Turn Signal"),
       tr_noop("Let an active turn signal below the lane-change speed hand speed control to the model.")),
      ("DynamicExperimentalTriggerStopLight", tr_noop("DEC: Stops Ahead"),
       tr_noop("Let a predicted stop for a light or sign hand speed control to the model.")),
      ("DynamicExperimentalTriggerLowSpeed", tr_noop("DEC: Low Speed Creep"),
       tr_noop("Let creeping at very low speed hand speed control to the model.")),
    )
    self._dec_trigger_toggles = [
      toggle_item_sp(title=lambda t=title: tr(t), description=lambda d=desc: tr(d), param=param)
      for param, title, desc in self._dec_trigger_specs
    ]

    self._refresh_toggles = (
      ("AlphaLongitudinalEnabled", self._alpha_long_toggle),
      ("ExperimentalMode", self._experimental_toggle),
      ("ExperimentalModeSetSpeed", self._set_speed_toggle),
      ("ExperimentalModeLeadGap", self._lead_gap_toggle),
    )
    self.items = [item for _, item in self._refresh_toggles]

    ui_state.add_offroad_transition_callback(self.refresh)
    ui_state.add_engaged_transition_callback(self.refresh)

  def update_state(self):
    CP = ui_state.CP
    has_long = CP is not None and ui_state.has_longitudinal_control
    # CP is None means nothing has fingerprinted this car yet (fresh install, or /data
    # rebuilt after a factory reset). Hiding the row then reads as "the feature is gone",
    # which is exactly how it looked after the rebuild, while the car may well support it.
    # Keep it on screen and dead until a drive fills CP in; hide it only when a car we
    # have actually seen does not offer alpha longitudinal.
    alpha_available = CP is not None and CP.alphaLongitudinalAvailable
    self._alpha_long_toggle.set_visible(alpha_available or CP is None)
    self._alpha_long_toggle.action_item.set_enabled(alpha_available and ui_state.is_offroad())
    # Experimental Mode runs on openpilot longitudinal control and both selfdrived and
    # ui_state._enforce_constraints delete the key when there is none, so accepting the
    # tap only to flip back -- which is what `CP is None or` allowed -- is a lie. has_long
    # is the same condition those two enforce.
    self._experimental_toggle.action_item.set_enabled(has_long)
    self._dec_toggle.action_item.set_enabled(has_long)
    # DEC decides the mode on its own, and the e2e assists never act under it
    dec = self._dec_toggle.action_item.get_state()
    self._set_speed_toggle.action_item.set_enabled(has_long and not dec)
    self._lead_gap_toggle.action_item.set_enabled(has_long and not dec)

  def refresh(self):
    for key, item in self._refresh_toggles:
      item.action_item.set_state(ui_state.params.get_bool(key))

  @staticmethod
  def _confirm(item, callback) -> None:
    content = f"<h1>{item.title}</h1><br><p>{item.description}</p>"
    # The store still holds the old value until the driver answers, so a switch that
    # follows the store would flip back behind the dialog. Paused for the dialog's life,
    # then re-read through the callback's own set_state/refresh path.
    toggle = item.action_item.toggle
    toggle.set_sync_paused(True)

    def on_result(result: DialogResult):
      toggle.set_sync_paused(False)
      callback(result)

    gui_app.push_widget(ConfirmDialog(content, tr("Enable"), rich=True, callback=on_result))

  def _on_alpha_long(self, state: bool):
    if not state:
      ui_state.set_alpha_longitudinal(False)
      return

    def on_result(result: DialogResult):
      if result == DialogResult.CONFIRM:
        ui_state.set_alpha_longitudinal(True)
      else:
        self._alpha_long_toggle.action_item.set_state(False)

    self._confirm(self._alpha_long_toggle, on_result)

  def _on_experimental_mode(self, state: bool):
    if not state or ui_state.params.get_bool("ExperimentalModeConfirmed"):
      self._apply_experimental_mode(state)
      return

    def on_result(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._apply_experimental_mode(True, acknowledged=True)
      else:
        self._experimental_toggle.action_item.set_state(False)

    self._confirm(self._experimental_toggle, on_result)

  def _apply_experimental_mode(self, enabled: bool, *, acknowledged: bool = False):
    """Write through the mode state machine, like the wheel buttons and
    carrot_server: Safe Mode lock, road-state prerequisite, read-back check.
    A refusal restores the drawn switch."""
    from openpilot.sunnypilot.common.mode_state_runtime import ModeStateError, set_experimental_mode

    try:
      set_experimental_mode(ui_state.params, enabled, acknowledged=acknowledged)
    except ModeStateError as exc:
      self._experimental_toggle.action_item.set_state(not enabled)
      gui_app.push_widget(alert_dialog(str(exc)))
      return
    ui_state.set_experimental_mode(enabled)  # syncs the offroad cache
