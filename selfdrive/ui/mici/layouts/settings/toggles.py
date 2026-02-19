import pyray as rl
from collections.abc import Callable
from cereal import log

from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle, BigMultiToggle
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import NavWidget
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
IQ_LONG_OPTION = "IQ.Pilot Long Control"
STOCK_ACC_OPTION = "Stock ACC"
IQ_MODE_OPTION = "IQ.Pilot"
TACC_OPTION = "TACC"


class TogglesLayoutMici(NavWidget):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self.set_back_callback(back_callback)
    # Keep IQ.Pilot enabled by default; the UI no longer exposes this toggle.
    ui_state.params.put_bool("OpenpilotEnabledToggle", True)

    self._personality_toggle = BigMultiParamToggle("driving personality", "LongitudinalPersonality", ["aggressive", "standard", "relaxed"])
    aol_toggle = BigParamControl("always on lateral (AOL)", "Mads")
    self._longitudinal_control_selector = BigMultiToggle(
      "longitudinal control",
      [IQ_LONG_OPTION, STOCK_ACC_OPTION],
      select_callback=self._on_longitudinal_control_selection,
    )
    self._longitudinal_mode_selector = BigMultiToggle(
      "Long Mode",
      [IQ_MODE_OPTION, TACC_OPTION],
      select_callback=self._on_longitudinal_mode_selection,
    )
    # Keep selector typography compact enough for long labels.
    self._longitudinal_control_selector._label.set_font_size(26)
    self._longitudinal_control_selector._sub_label.set_font_size(24)
    self._longitudinal_mode_selector._label.set_font_size(26)
    self._longitudinal_mode_selector._sub_label.set_font_size(24)
    is_metric_toggle = BigParamControl("use metric units", "IsMetric")
    ldw_toggle = BigParamControl("lane departure warnings", "IsLdwEnabled")
    always_on_dm_toggle = BigParamControl("always-on driver monitor", "AlwaysOnDM")
    record_front = BigParamControl("record & upload driver camera", "RecordFront", toggle_callback=restart_needed_callback)

    self._scroller = Scroller([
      self._longitudinal_control_selector,
      self._longitudinal_mode_selector,
      self._personality_toggle,
      aol_toggle,
      is_metric_toggle,
      ldw_toggle,
      always_on_dm_toggle,
      record_front,
    ], snap_items=False)

    # Toggle lists
    self._refresh_toggles = (
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("RecordFront", record_front),
      ("Mads", aol_toggle),
    )

    self._longitudinal_control_selector.set_enabled(lambda: not ui_state.engaged)
    aol_toggle.set_enabled(lambda: ui_state.is_offroad())
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      alpha_available = ui_state.CP.alphaLongitudinalAvailable and not ui_state.is_release
      self._longitudinal_control_selector.set_visible(alpha_available)
      if not alpha_available:
        self._longitudinal_control_selector.set_value(STOCK_ACC_OPTION)
        ui_state.params.remove("AlphaLongitudinalEnabled")

      alpha_long_enabled = ui_state.params.get_bool("AlphaLongitudinalEnabled")
      tacc_visible = ui_state.has_longitudinal_control and alpha_long_enabled

      if ui_state.has_longitudinal_control:
        if tacc_visible and ui_state.params.get("ExperimentalMode") is None:
          # Default IQ.Pilot longitudinal to end-to-end behavior on first enable.
          ui_state.params.put_bool("ExperimentalMode", True)
        self._longitudinal_mode_selector.set_visible(tacc_visible)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._longitudinal_mode_selector.set_visible(False)
        self._longitudinal_mode_selector.set_value(IQ_MODE_OPTION)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")
    else:
      self._longitudinal_control_selector.set_visible(False)
      self._longitudinal_mode_selector.set_visible(False)

    self._longitudinal_control_selector.set_value(IQ_LONG_OPTION if ui_state.params.get_bool("AlphaLongitudinalEnabled") else STOCK_ACC_OPTION)
    self._longitudinal_mode_selector.set_value(IQ_MODE_OPTION if ui_state.params.get_bool("ExperimentalMode") else TACC_OPTION)

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))

  def _on_longitudinal_control_selection(self, value: str):
    enable_iq_long = value == IQ_LONG_OPTION
    if enable_iq_long == ui_state.params.get_bool("AlphaLongitudinalEnabled"):
      return

    ui_state.params.put_bool("AlphaLongitudinalEnabled", enable_iq_long)
    if enable_iq_long:
      # Default to end-to-end IQ.Pilot when enabling IQ.Pilot longitudinal control.
      ui_state.params.put_bool("ExperimentalMode", True)
    restart_needed_callback(enable_iq_long)
    self._update_toggles()

  def _on_longitudinal_mode_selection(self, value: str):
    # IQ.Pilot => ExperimentalMode=True, TACC => ExperimentalMode=False
    ui_state.params.put_bool("ExperimentalMode", value == IQ_MODE_OPTION)
    self._update_toggles()

  def _render(self, rect: rl.Rectangle):
    self._scroller.render(rect)
