#!/usr/bin/env python3
import subprocess
import sys
import time
import threading
from enum import IntEnum

import raylib_nb as rl

from openpilot.common.hardware import HARDWARE, PC
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.system.ui.mici_setup import GreyBigButton, FailedPage
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigConfirmationCircleButton

USERDATA = "/dev/disk/by-partlabel/userdata"
TIMEOUT = 3*60

# Strings are hardcoded Simplified Chinese on purpose: the reset screen must
# come up in Chinese no matter what LanguageSetting says (it can be English,
# and a factory reset wipes it anyway), so tr() is deliberately not used here.
TEXT_FAILED_TITLE = "重置失败"
TEXT_FAILED_SUBTITLE = "请重启以重试"
TEXT_RESETTING_TITLE = "正在重置设备"
TEXT_RESETTING_SUBTITLE = "最多需要\n一分钟..."
TEXT_RESETTING_DOTS = "最多需要\n一分钟{dots}"
TEXT_RESET_ERASE = "重置并\n清除"
TEXT_CANCEL = "取消"
TEXT_REBOOT_DEVICE = "重启\n设备"
TEXT_FACTORY_RESET = "恢复出厂设置"
TEXT_RESET_ERASE_DESC = "重置将清除\n所有用户内容与数据"
TEXT_ERASE_NOTICE = "重置会擦除所有用户内容和数据。"
TEXT_UNMOUNTED = "用户数据分区\n无法挂载"
TEXT_TAP_RESET = "由点按屏幕\n触发的重置"
TEXT_DEEPER_RESET = "如需彻底重置，请访问\nhttps://flash.comma.ai"


class ResetMode(IntEnum):
  USER_RESET = 0  # user initiated a factory reset from openpilot
  RECOVER = 1     # userdata is corrupt for some reason, give a chance to recover
  TAP_RESET = 2   # user initiated a factory reset by tapping the screen during boot


class ResetFailedPage(FailedPage):
  def __init__(self):
    super().__init__(None, TEXT_FAILED_TITLE, TEXT_FAILED_SUBTITLE, icon="icons_mici/setup/reset_failed.png")

  def show_event(self):
    super().show_event()
    self._nav_bar._alpha = 0.0  # not dismissable

  def _back_enabled(self) -> bool:
    return False


class ResettingPage(BigDialog):
  DOT_STEP = 0.6

  def __init__(self):
    super().__init__(TEXT_RESETTING_TITLE, TEXT_RESETTING_SUBTITLE,
                     gui_app.texture("icons_mici/setup/factory_reset.png", 64, 64))
    self._show_time = 0.0

  def show_event(self):
    super().show_event()
    self._nav_bar._alpha = 0.0  # not dismissable
    self._show_time = rl.get_time()

  def _back_enabled(self) -> bool:
    return False

  def _render(self, _):
    t = (rl.get_time() - self._show_time) % (self.DOT_STEP * 2)
    dots = "." * min(int(t / (self.DOT_STEP / 4)), 3)
    self._card.set_value(TEXT_RESETTING_DOTS.format(dots=dots))
    super()._render(_)


class Reset(Scroller):
  def __init__(self, mode):
    super().__init__()
    self._mode = mode
    self._previous_active_widget = None
    self._reset_failed = False
    self._timeout_st = time.monotonic()

    self._resetting_page = ResettingPage()
    self._reset_failed_page = ResetFailedPage()

    self._reset_button = BigConfirmationCircleButton(TEXT_RESET_ERASE, gui_app.texture("icons_mici/settings/device/uninstall.png", 70, 70),
                                                     self._start_reset, exit_on_confirm=False, red=True)
    self._cancel_button = BigConfirmationCircleButton(TEXT_CANCEL, gui_app.texture("icons_mici/setup/cancel.png", 64, 64),
                                                      gui_app.request_close, exit_on_confirm=False)
    self._reboot_button = BigConfirmationCircleButton(TEXT_REBOOT_DEVICE, gui_app.texture("icons_mici/settings/device/reboot.png", 64, 70),
                                                      HARDWARE.reboot, exit_on_confirm=False)

    # show reboot button if in recover mode
    self._cancel_button.set_visible(mode != ResetMode.RECOVER)
    self._reboot_button.set_visible(mode == ResetMode.RECOVER)

    main_card = GreyBigButton(TEXT_FACTORY_RESET, TEXT_RESET_ERASE_DESC,
                              gui_app.texture("icons_mici/setup/factory_reset.png", 64, 64))
    self._scroller.add_widget(main_card)

    if mode != ResetMode.USER_RESET:
      self._scroller.add_widget(GreyBigButton("", TEXT_ERASE_NOTICE))
      if mode == ResetMode.RECOVER:
        main_card.set_value(TEXT_UNMOUNTED)
      elif mode == ResetMode.TAP_RESET:
        main_card.set_value(TEXT_TAP_RESET)

    self._scroller.add_widgets([
      GreyBigButton("", TEXT_DEEPER_RESET),
      self._cancel_button,
      self._reboot_button,
      self._reset_button,
    ])

    gui_app.add_nav_stack_tick(self._nav_stack_tick)

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
      self._reset_failed = True

  def _start_reset(self):
    def do_erase_thread():
      threading.Thread(target=self._do_erase, daemon=True).start()

    self._resetting_page.set_shown_callback(do_erase_thread)
    gui_app.push_widget(self._resetting_page)

  def _nav_stack_tick(self):
    if self._reset_failed:
      self._reset_failed = False
      gui_app.pop_widgets_to(self, lambda: gui_app.push_widget(self._reset_failed_page))

    active_widget = gui_app.get_active_widget()
    if active_widget != self._previous_active_widget:
      self._previous_active_widget = active_widget
      self._timeout_st = time.monotonic()
    elif self._mode != ResetMode.RECOVER and active_widget != self._resetting_page and (time.monotonic() - self._timeout_st) > TIMEOUT:
      exit(0)


def main():
  mode = ResetMode.USER_RESET
  if len(sys.argv) > 1:
    if sys.argv[1] == '--recover':
      mode = ResetMode.RECOVER
    elif sys.argv[1] == '--tap-reset':
      mode = ResetMode.TAP_RESET

  gui_app.init_window("系统重置")
  reset = Reset(mode)
  gui_app.push_widget(reset)

  for _ in gui_app.render():
    pass


if __name__ == "__main__":
  main()
