#!/usr/bin/env python3
import subprocess
import sys
import threading
import time
from enum import IntEnum

import raylib_nb as rl

from openpilot.common.hardware import PC
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.label import UnifiedLabel, gui_label

USERDATA = "/dev/disk/by-partlabel/userdata"
TIMEOUT = 3*60

# Strings are hardcoded Simplified Chinese on purpose: the reset screen must
# come up in Chinese no matter what LanguageSetting says (it can be English,
# and a factory reset wipes it anyway), so tr() is deliberately not used here.
TEXT_TITLE = "系统重置"
TEXT_CONFIRM_BODY = "确定要重置设备吗？"
TEXT_RESETTING_BODY = "正在重置设备...\n最多需要一分钟。"
TEXT_FAILED_BODY = "重置失败。请重启以重试。"
TEXT_RECOVER_BODY = "无法挂载数据分区,分区可能已损坏。按确认以擦除并重置设备。"
TEXT_TRIGGERED_BODY = "已触发系统重置。按确认将清除所有内容和设置。按取消可继续启动。"
TEXT_CANCEL = "取消"
TEXT_CONFIRM = "确认"
TEXT_REBOOT = "重启"


class ResetMode(IntEnum):
  USER_RESET = 0  # user initiated a factory reset from openpilot
  RECOVER = 1     # userdata is corrupt for some reason, give a chance to recover


class ResetState(IntEnum):
  NONE = 0
  CONFIRM = 1
  RESETTING = 2
  FAILED = 3


class Reset(Widget):
  def __init__(self, mode):
    super().__init__()
    self._mode = mode
    self._previous_reset_state = None
    self._reset_state = ResetState.NONE
    self._cancel_button = Button(TEXT_CANCEL, gui_app.request_close)
    self._confirm_button = Button(TEXT_CONFIRM, self._confirm, button_style=ButtonStyle.PRIMARY)
    self._reboot_button = Button(TEXT_REBOOT, self._reboot)
    self._body_label = UnifiedLabel(self._get_body_text, 90, line_height=1 / 0.9)

  @staticmethod
  def _reboot() -> None:
    subprocess.run("sudo reboot", shell=True)

  def _do_erase(self):
    if PC:
      return

    # Removing data and formatting
    rm = subprocess.run("sudo rm -rf /data/*", shell=True).returncode
    subprocess.run(f"sudo umount {USERDATA}", shell=True)
    fmt = subprocess.run(f"yes | sudo mkfs.ext4 {USERDATA}", shell=True).returncode

    if rm == 0 or fmt == 0:
      subprocess.run("sudo reboot", shell=True)
    else:
      self._reset_state = ResetState.FAILED

  def _start_reset(self):
    self._reset_state = ResetState.RESETTING
    threading.Timer(0.1, self._do_erase).start()

  def _update_state(self):
    if self._reset_state != self._previous_reset_state:
      self._previous_reset_state = self._reset_state
      self._timeout_st = time.monotonic()
    elif self._reset_state != ResetState.RESETTING and (time.monotonic() - self._timeout_st) > TIMEOUT:
      exit(0)

  def _render(self, _):
    content_rect = rl.Rectangle(45, 200, self._rect.width - 90, self._rect.height - 245)

    label_rect = rl.Rectangle(content_rect.x + 140, content_rect.y, content_rect.width - 280, 100 * FONT_SCALE)
    gui_label(label_rect, TEXT_TITLE, 100, font_weight=FontWeight.BOLD)

    text_rect = rl.Rectangle(content_rect.x + 140, content_rect.y + 140, content_rect.width - 280, content_rect.height - 90 - 100 * FONT_SCALE)
    self._body_label.render(text_rect)

    button_height = 160
    button_spacing = 50
    button_top = content_rect.y + content_rect.height - button_height
    button_width = (content_rect.width - button_spacing) / 2.0

    if self._reset_state != ResetState.RESETTING:
      if self._mode == ResetMode.RECOVER:
        self._reboot_button.render(rl.Rectangle(content_rect.x, button_top, button_width, button_height))
      elif self._mode == ResetMode.USER_RESET:
        self._cancel_button.render(rl.Rectangle(content_rect.x, button_top, button_width, button_height))

      if self._reset_state != ResetState.FAILED:
        self._confirm_button.render(rl.Rectangle(content_rect.x + button_width + 50, button_top, button_width, button_height))
      else:
        self._reboot_button.render(rl.Rectangle(content_rect.x, button_top, content_rect.width, button_height))

  def _confirm(self):
    if self._reset_state == ResetState.CONFIRM:
      self._start_reset()
    else:
      self._reset_state = ResetState.CONFIRM

  def _get_body_text(self):
    if self._reset_state == ResetState.CONFIRM:
      return TEXT_CONFIRM_BODY
    if self._reset_state == ResetState.RESETTING:
      return TEXT_RESETTING_BODY
    if self._reset_state == ResetState.FAILED:
      return TEXT_FAILED_BODY
    if self._mode == ResetMode.RECOVER:
      return TEXT_RECOVER_BODY
    return TEXT_TRIGGERED_BODY


def main():
  mode = ResetMode.USER_RESET
  if len(sys.argv) > 1:
    if sys.argv[1] == '--recover':
      mode = ResetMode.RECOVER

  gui_app.init_window("系统重置", 20)
  reset = Reset(mode)

  gui_app.push_widget(reset)

  for _ in gui_app.render():
    pass


if __name__ == "__main__":
  main()
