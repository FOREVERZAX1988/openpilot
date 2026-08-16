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

    self.items = [
      self.start_stop,
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

  def update_settings(self):
    if ui_state.CP is not None:
      # 仅 Macan(MLB) 支持；其他 VW 平台隐藏开关
      is_macan = ui_state.CP.carFingerprint == "PORSCHE_MACAN_MK1"
      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.action_item.set_visible(is_macan)
