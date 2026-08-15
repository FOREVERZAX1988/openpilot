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
    'Macan 起步跟停：开启后，跟车/红灯停车由视觉模型判定起步时机，'
    'OP 自动代发 RESUME 信号解除原厂停车保持态并起步（带提示音）。'
    '关闭时，停车后需轻踩油门/SET/RESUME 恢复起步（原厂行为）。'
  )
}


class VolkswagenSettings(BrandSettings):
  def __init__(self):
    super().__init__()

    self.start_stop = toggle_item_sp(
      lambda: tr("起步跟停（Stop and Go）"),
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
