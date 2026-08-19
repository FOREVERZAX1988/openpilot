"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp


DESCRIPTIONS = {
  'start_stop': tr_noop(
    'Macan Stop and Go: when enabled, the vision model decides when to start, '
    'and openpilot sends the RESUME signal to release the stock parking hold '
    '(with a chime). When disabled, gently press the gas or SET/RESUME to '
    'resume (stock behavior).'
  ),
  'slope_comp': tr_noop(
    'Macan Slope Compensation: when enabled, the IMU slope signal adds '
    'g*sin(slope) to the acceleration request - more torque uphill, and a '
    'brake tap downhill (prevents forward lurch). Default off = stock '
    'behavior. Onroad cycle restart is requested after toggling.'
  ),
  'slope_comp_unlimited': tr_noop(
    'Macan Slope Comp Unlimited (sub-option): when Slope Compensation is ON, '
    'this removes the stock torque cap (option 2: min(max(stock_mom, 200))), '
    'giving small slopes room to act. When OFF, the stock cap applies '
    '(option 1: min(stock_mom)).'
  ),
  'steer_params': tr_noop(
    'Macan Steering Params (experimental): when enabled, uses calibrated '
    'steerRatio 18.0 / friction 0.52 instead of stock values. Calibration '
    'shows 22% cross-route spread and latAccelFactor data is insufficient, '
    'so this is EXPERIMENTAL - keep off until field data confirms.'
  )
}


class VolkswagenSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    self.start_stop = toggle_item_sp(
      lambda: tr("Stop and Go (Macan)"),
      description=lambda: tr(DESCRIPTIONS["start_stop"]),
      initial_state=ui_state.params.get_bool("MacanStartStop"),
      callback=self._on_enable_start_stop,
      enabled=lambda: not ui_state.engaged,
    )

    self.slope_comp = toggle_item_sp(
      lambda: tr("Slope Compensation (Macan)"),
      description=lambda: tr(DESCRIPTIONS["slope_comp"]),
      initial_state=ui_state.params.get_bool("MacanSlopeComp"),
      callback=self._on_enable_slope_comp,
      enabled=lambda: not ui_state.engaged,
    )

    self.slope_comp_unlimited = toggle_item_sp(
      lambda: tr("Slope Comp Unlimited (Macan)"),
      description=lambda: tr(DESCRIPTIONS["slope_comp_unlimited"]),
      initial_state=ui_state.params.get_bool("MacanSlopeCompUnlimited"),
      callback=self._on_enable_slope_comp_unlimited,
      enabled=lambda: not ui_state.engaged,
    )

    self.steer_params = toggle_item_sp(
      lambda: tr("Steering Params (Macan)"),
      description=lambda: tr(DESCRIPTIONS["steer_params"]),
      initial_state=ui_state.params.get_bool("MacanSteerParams"),
      callback=self._on_enable_steer_params,
      enabled=lambda: not ui_state.engaged,
    )

    self.items = [
      self.start_stop,
      self.slope_comp,
      self.slope_comp_unlimited,
      self.steer_params,
    ]

  def _on_enable_start_stop(self, state: bool):
    if state:
      def confirm_callback(result: int):
        if result == DialogResult.CONFIRM:
          ui_state.params.put_bool("MacanStartStop", True)
          ui_state.params.put_bool("OnroadCycleRequested", True)
        else:
          self.start_stop.action_item.set_state(False)

      content = (f"<h1>{self.start_stop.title}</h1><br>" +
                 f"<p>{self.start_stop.description}</p>")

      dlg = ConfirmDialog(content, tr("Enable"), rich=True, callback=confirm_callback)
      gui_app.push_widget(dlg)

    else:
      ui_state.params.put_bool("MacanStartStop", False)
      ui_state.params.put_bool("OnroadCycleRequested", True)

  def _on_enable_slope_comp(self, state: bool):
    ui_state.params.put_bool("MacanSlopeComp", state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def _on_enable_slope_comp_unlimited(self, state: bool):
    ui_state.params.put_bool("MacanSlopeCompUnlimited", state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def _on_enable_steer_params(self, state: bool):
    ui_state.params.put_bool("MacanSteerParams", state)
    ui_state.params.put_bool("OnroadCycleRequested", True)

  def update_settings(self):
    if ui_state.CP is not None:
      # 仅 Macan(MLB) 支持；其他 VW 平台隐藏开关
      is_macan = ui_state.CP.carFingerprint == "PORSCHE_MACAN_MK1"
      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.action_item.set_visible(is_macan)
      for item in (self.slope_comp, self.slope_comp_unlimited, self.steer_params):
        item.action_item.set_enabled(is_macan and not ui_state.engaged)
        item.action_item.set_visible(is_macan)
