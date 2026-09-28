"""
Copyright (c) 2026, Macan EPS Assist Compensation settings (sunnypilot UI)

EPS 助力补偿设置（Macan 专属）
- DpEpsAssistComp：EPS 助力曲线补偿开关（0=关闭/原版手感，1=开启）
- DpEpsAssistCompScale：补偿幅度（1.00=MQB 全量，0.50=半量；0.00 危险勿用）
"""
from collections.abc import Callable

import pyray as rl

from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, option_item_sp
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.selfdrive.ui.ui_state import ui_state


class EpsSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._eps_comp_toggle = toggle_item_sp(
      param="DpEpsAssistComp",
      title=lambda: tr("EPS Assist Compensation"),
      description=lambda: tr("Compensate for the EPS speed-dependent assist curve (the EPS absorbs part of the "
                             "steering command at low speed). Disable to compare with stock steering feel."),
    )
    self._eps_comp_scale = option_item_sp(
      param="DpEpsAssistCompScale",
      title=lambda: tr("EPS Compensation Scale"),
      min_value=0,
      max_value=160,
      value_change_step=5,
      use_float_scaling=True,
      description=lambda: tr("Compensation amount: 1.00 = full MQB curve (low speed x1.6), 0.50 = half. "
                             "WARNING: 0.00 zeroes steering output — use the toggle above to disable instead."),
      label_callback=lambda v: f"{v / 100.0:.2f}x",
    )
    return [
      self._eps_comp_toggle,
      self._eps_comp_scale,
    ]

  def _update_state(self):
    super()._update_state()
    self._eps_comp_toggle.action_item.set_enabled(ui_state.is_offroad())
    self._eps_comp_scale.action_item.set_enabled(ui_state.is_offroad())

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    content_rect = rl.Rectangle(rect.x, rect.y + self._back_button.rect.height + 40, rect.width,
                                rect.height - self._back_button.rect.height - 40)
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()
