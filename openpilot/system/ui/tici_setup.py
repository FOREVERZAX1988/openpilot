#!/usr/bin/env python3
import os
import re
import threading
import time
import urllib.request
from enum import IntEnum

import raylib_nb as rl

from openpilot.cereal import log
from openpilot.common.hardware import HARDWARE
from openpilot.system.ui.lib.git_installer import GitInstallError, install_from_git, resolve_git_repo
from openpilot.system.ui.lib.scroll_panel import GuiScrollPanel
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE, TextAlignment, TextAlignmentVertical
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.button import Button, ButtonStyle, ButtonRadio
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.label import Label
from openpilot.system.ui.widgets.network import WifiManagerUI, WifiManager

NetworkType = log.DeviceState.NetworkType

MARGIN = 50
TITLE_FONT_SIZE = 90
TITLE_FONT_WEIGHT = FontWeight.MEDIUM
NEXT_BUTTON_WIDTH = 310
BODY_FONT_SIZE = 80
BUTTON_HEIGHT = 160
BUTTON_SPACING = 50

OPENPILOT_URL = "https://openpilot.comma.ai"

# comma.sh only re-checks /data/continue.sh after /tmp/installer shows up and
# exits; git installs write a no-op installer there to unblock the boot loop.
INSTALLER_DESTINATION_PATH = "/tmp/installer"


class SetupState(IntEnum):
  LOW_VOLTAGE = 0
  GETTING_STARTED = 1
  NETWORK_SETUP = 2
  SOFTWARE_SELECTION = 3
  CUSTOM_SOFTWARE = 4
  DOWNLOADING = 5
  DOWNLOAD_FAILED = 6
  CUSTOM_SOFTWARE_WARNING = 7


class Setup(Widget):
  def __init__(self):
    super().__init__()
    self.state = SetupState.GETTING_STARTED
    self.network_check_thread = None
    self.network_connected = threading.Event()
    self.wifi_connected = threading.Event()
    self.stop_network_check_thread = threading.Event()
    self.failed_url = ""
    self.failed_reason = ""
    self.download_url = ""
    self.download_progress = 0
    self.download_status = tr("Downloading...")
    self._git_status_texts = {
      "clone": tr("Cloning repository..."),
      "submodules": tr("Fetching submodules..."),
      "lfs": tr("Fetching LFS files..."),
      "install": tr("Installing openpilot..."),
    }
    self._git_error_texts = {
      "git_missing": tr("Ensure the entered URL is valid, and the device's internet connection is good."),
      "git_failed": tr("Git clone failed. Check the repository, branch and network."),
      "clone_failed": tr("Git clone failed. Check the repository, branch and network."),
      "submodule_failed": tr("Fetching submodules failed. Check the network."),
      "lfs_failed": tr("Fetching LFS files failed. Check the network."),
      "not_openpilot": tr("Not a valid openpilot repository."),
      "install_failed": tr("Failed to install openpilot. Check free space in /data."),
    }
    self.download_thread = None
    self.wifi_ui = WifiManagerUI(WifiManager())
    self.keyboard = Keyboard()
    self.selected_radio = None
    self.warning = gui_app.texture("icons/warning.png", 150, 150)
    self.checkmark = gui_app.texture("icons/circled_check.png", 100, 100)

    self._low_voltage_title_label = Label(tr("WARNING: Low Voltage"), TITLE_FONT_SIZE, FontWeight.MEDIUM, TextAlignment.LEFT,
                                          text_color=rl.Color(255, 89, 79, 255), text_padding=20)
    self._low_voltage_body_label = Label(tr("Power your device in a car with a harness or proceed at your own risk."), BODY_FONT_SIZE,
                                         text_alignment=TextAlignment.LEFT, text_padding=20)
    self._low_voltage_continue_button = Button(tr("Continue"), self._low_voltage_continue_button_callback)
    self._low_voltage_poweroff_button = Button(tr("Power Off"), HARDWARE.shutdown)

    self._getting_started_button = Button("", self._getting_started_button_callback, button_style=ButtonStyle.PRIMARY, border_radius=0)
    self._getting_started_title_label = Label(tr("Getting Started"), TITLE_FONT_SIZE, FontWeight.BOLD, TextAlignment.LEFT, text_padding=20)
    self._getting_started_body_label = Label(tr("Before we get on the road, let's finish installation and cover some details."),
                                             BODY_FONT_SIZE, text_alignment=TextAlignment.LEFT, text_padding=20)

    self._software_selection_openpilot_button = ButtonRadio("openpilot", self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._software_selection_custom_software_button = ButtonRadio(tr("Custom Software"), self.checkmark, font_size=BODY_FONT_SIZE, text_padding=80)
    self._software_selection_continue_button = Button(tr("Continue"), self._software_selection_continue_button_callback,
                                                      button_style=ButtonStyle.PRIMARY)
    self._software_selection_continue_button.set_enabled(False)
    self._software_selection_back_button = Button(tr("Back"), self._software_selection_back_button_callback)
    self._software_selection_title_label = Label(tr("Choose Software to Use"), TITLE_FONT_SIZE, FontWeight.BOLD, TextAlignment.LEFT,
                                                 text_padding=20)
    # AGNOS 版本显示在标题行右侧（/VERSION 即 AGNOS 版本号，如 20.6.16）
    self._software_selection_version_label = Label(f"AGNOS {HARDWARE.get_os_version()}", 54, FontWeight.NORMAL, TextAlignment.RIGHT,
                                                   text_color=rl.Color(170, 170, 170, 255), text_padding=20)

    self._download_failed_reboot_button = Button(tr("Reboot device"), HARDWARE.reboot)
    self._download_failed_startover_button = Button(tr("Start over"), self._download_failed_startover_button_callback, button_style=ButtonStyle.PRIMARY)
    self._download_failed_title_label = Label(tr("Download Failed"), TITLE_FONT_SIZE, FontWeight.BOLD, TextAlignment.LEFT, text_padding=20)
    self._download_failed_url_label = Label("", 52, FontWeight.NORMAL, TextAlignment.LEFT, text_padding=20)
    self._download_failed_body_label = Label("", BODY_FONT_SIZE, text_alignment=TextAlignment.LEFT, text_padding=20)

    self._network_setup_back_button = Button(tr("Back"), self._network_setup_back_button_callback)
    self._network_setup_continue_button = Button(tr("Waiting for internet"), self._network_setup_continue_button_callback,
                                                 button_style=ButtonStyle.PRIMARY)
    self._network_setup_continue_button.set_enabled(False)
    self._network_setup_title_label = Label(tr("Connect to Wi-Fi"), TITLE_FONT_SIZE, FontWeight.BOLD, TextAlignment.LEFT, text_padding=20)

    self._custom_software_warning_continue_button = Button(tr("Scroll to continue"), self._custom_software_warning_continue_button_callback,
                                                           button_style=ButtonStyle.PRIMARY)
    self._custom_software_warning_continue_button.set_enabled(False)
    self._custom_software_warning_back_button = Button(tr("Back"), self._custom_software_warning_back_button_callback)
    self._custom_software_warning_title_label = Label(tr("WARNING: Custom Software"), 81, FontWeight.BOLD, TextAlignment.LEFT,
                                                      text_color=rl.Color(255, 89, 79, 255),
                                                      text_padding=60)
    self._yellow_warning_icon = gui_app.texture("icons/yellow_warning.png", int(68 * FONT_SCALE), int(68 * FONT_SCALE))
    self._custom_software_warning_body_labels = [
      Label(text, 68, text_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
            text_alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP,
            text_padding=60, icon=self._yellow_warning_icon if has_icon else None)
      for text, has_icon in [
        (tr("Use caution when installing third-party software."), False),
        (tr("It has not been tested by comma."), True),
        (tr("It may not comply with relevant safety standards."), True),
        (tr("It may cause damage to your device and/or vehicle."), True),
        (tr("If you'd like to proceed, use https://flash.comma.ai to restore your device to a factory state later."), False)
      ]
    ]

    self._custom_software_warning_body_scroll_panel = GuiScrollPanel()

    self._downloading_body_label = Label(tr("Downloading..."), TITLE_FONT_SIZE, FontWeight.MEDIUM, text_padding=20)

    try:
      with open("/sys/class/hwmon/hwmon1/in1_input") as f:
        voltage = float(f.read().strip()) / 1000.0
        if voltage < 7:
          self.state = SetupState.LOW_VOLTAGE
    except (FileNotFoundError, ValueError):
      self.state = SetupState.LOW_VOLTAGE

  def _render(self, rect: rl.Rectangle):
    if self.state == SetupState.LOW_VOLTAGE:
      self.render_low_voltage(rect)
    elif self.state == SetupState.GETTING_STARTED:
      self.render_getting_started(rect)
    elif self.state == SetupState.NETWORK_SETUP:
      self.render_network_setup(rect)
    elif self.state == SetupState.SOFTWARE_SELECTION:
      self.render_software_selection(rect)
    elif self.state == SetupState.CUSTOM_SOFTWARE_WARNING:
      self.render_custom_software_warning(rect)
    elif self.state == SetupState.CUSTOM_SOFTWARE:
      self.render_custom_software()
    elif self.state == SetupState.DOWNLOADING:
      self.render_downloading(rect)
    elif self.state == SetupState.DOWNLOAD_FAILED:
      self.render_download_failed(rect)

  def _low_voltage_continue_button_callback(self):
    self.state = SetupState.GETTING_STARTED

  def _custom_software_warning_back_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _custom_software_warning_continue_button_callback(self):
    self.state = SetupState.NETWORK_SETUP
    self.stop_network_check_thread.clear()
    self.start_network_check()

  def _getting_started_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _software_selection_back_button_callback(self):
    self.state = SetupState.GETTING_STARTED

  def _software_selection_continue_button_callback(self):
    if self._software_selection_openpilot_button.selected:
      self.state = SetupState.NETWORK_SETUP
      self.stop_network_check_thread.clear()
      self.start_network_check()
    else:
      self.state = SetupState.CUSTOM_SOFTWARE_WARNING

  def _download_failed_startover_button_callback(self):
    self.state = SetupState.GETTING_STARTED

  def _network_setup_back_button_callback(self):
    self.state = SetupState.SOFTWARE_SELECTION

  def _network_setup_continue_button_callback(self):
    self.stop_network_check_thread.set()
    if self._software_selection_openpilot_button.selected:
      # git install straight from comma's master (host probe + gh-proxy fallback)
      self.download("commaai/master")
    else:
      self.state = SetupState.CUSTOM_SOFTWARE

  def render_low_voltage(self, rect: rl.Rectangle):
    rl.draw_texture_ex(self.warning, rl.Vector2(rect.x + 150, rect.y + 110), 0.0, 1.0, rl.WHITE)

    self._low_voltage_title_label.render(rl.Rectangle(rect.x + 150, rect.y + 110 + 150 + 100, rect.width - 500 - 150, TITLE_FONT_SIZE * FONT_SCALE))
    self._low_voltage_body_label.render(rl.Rectangle(rect.x + 150, rect.y + 110 + 150 + 150, rect.width - 500, BODY_FONT_SIZE * FONT_SCALE * 3))

    button_width = (rect.width - MARGIN * 3) / 2
    button_y = rect.height - MARGIN - BUTTON_HEIGHT
    self._low_voltage_poweroff_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._low_voltage_continue_button.render(rl.Rectangle(rect.x + MARGIN * 2 + button_width, button_y, button_width, BUTTON_HEIGHT))

  def render_getting_started(self, rect: rl.Rectangle):
    self._getting_started_title_label.render(rl.Rectangle(rect.x + 165, rect.y + 280, rect.width - 265, TITLE_FONT_SIZE * FONT_SCALE))
    self._getting_started_body_label.render(rl.Rectangle(rect.x + 165, rect.y + 280 + TITLE_FONT_SIZE * FONT_SCALE, rect.width - 500,
                                                         BODY_FONT_SIZE * FONT_SCALE * 3))

    btn_rect = rl.Rectangle(rect.width - NEXT_BUTTON_WIDTH, 0, NEXT_BUTTON_WIDTH, rect.height)
    self._getting_started_button.render(btn_rect)
    triangle = gui_app.texture("images/button_continue_triangle.png", 54, int(btn_rect.height))
    rl.draw_texture_v(triangle, rl.Vector2(btn_rect.x + btn_rect.width / 2 - triangle.width / 2, btn_rect.height / 2 - triangle.height / 2), rl.WHITE)

  def check_network_connectivity(self):
    while not self.stop_network_check_thread.is_set():
      if self.state == SetupState.NETWORK_SETUP:
        try:
          urllib.request.urlopen(OPENPILOT_URL, timeout=2.0)
          self.network_connected.set()
          if HARDWARE.get_network_type() == NetworkType.wifi:
            self.wifi_connected.set()
          else:
            self.wifi_connected.clear()
        except Exception:
          self.network_connected.clear()
      time.sleep(1.0)

  def start_network_check(self):
    if self.network_check_thread is None or not self.network_check_thread.is_alive():
      self.network_check_thread = threading.Thread(target=self.check_network_connectivity, daemon=True)
      self.network_check_thread.start()

  def close(self):
    if self.network_check_thread is not None:
      self.stop_network_check_thread.set()
      self.network_check_thread.join()

  def render_network_setup(self, rect: rl.Rectangle):
    self._network_setup_title_label.render(rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - MARGIN * 2, TITLE_FONT_SIZE * FONT_SCALE))

    wifi_rect = rl.Rectangle(rect.x + MARGIN, rect.y + TITLE_FONT_SIZE * FONT_SCALE + MARGIN + 25, rect.width - MARGIN * 2,
                             rect.height - TITLE_FONT_SIZE * FONT_SCALE - 25 - BUTTON_HEIGHT - MARGIN * 3)
    rl.draw_rectangle_rounded(wifi_rect, 0.05, 10, rl.Color(51, 51, 51, 255))
    wifi_content_rect = rl.Rectangle(wifi_rect.x + MARGIN, wifi_rect.y, wifi_rect.width - MARGIN * 2, wifi_rect.height)
    self.wifi_ui.render(wifi_content_rect)

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN

    self._network_setup_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))

    # Check network connectivity status
    continue_enabled = self.network_connected.is_set()
    self._network_setup_continue_button.set_enabled(continue_enabled)
    continue_text = (tr("Continue") if self.wifi_connected.is_set() else tr("Continue without Wi-Fi")) if continue_enabled else tr("Waiting for internet")
    self._network_setup_continue_button.set_text(continue_text)
    self._network_setup_continue_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_software_selection(self, rect: rl.Rectangle):
    title_row = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - MARGIN * 2, TITLE_FONT_SIZE * FONT_SCALE)
    self._software_selection_title_label.render(title_row)
    self._software_selection_version_label.render(title_row)

    radio_height = 230
    radio_spacing = 30

    self._software_selection_continue_button.set_enabled(False)

    openpilot_rect = rl.Rectangle(rect.x + MARGIN, rect.y + TITLE_FONT_SIZE * FONT_SCALE + MARGIN * 2, rect.width - MARGIN * 2, radio_height)
    self._software_selection_openpilot_button.render(openpilot_rect)

    if self._software_selection_openpilot_button.selected:
      self._software_selection_continue_button.set_enabled(True)
      self._software_selection_custom_software_button.selected = False

    custom_rect = rl.Rectangle(rect.x + MARGIN, rect.y + TITLE_FONT_SIZE * FONT_SCALE + MARGIN * 2 + radio_height + radio_spacing, rect.width - MARGIN * 2,
                               radio_height)
    self._software_selection_custom_software_button.render(custom_rect)

    if self._software_selection_custom_software_button.selected:
      self._software_selection_continue_button.set_enabled(True)
      self._software_selection_openpilot_button.selected = False

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN

    self._software_selection_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._software_selection_continue_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_downloading(self, rect: rl.Rectangle):
    status = self.download_status
    if self.download_progress > 0:
      status = f"{status}  {self.download_progress}%"
    self._downloading_body_label.set_text(status)
    self._downloading_body_label.render(rl.Rectangle(rect.x, rect.y + rect.height / 2 - TITLE_FONT_SIZE * FONT_SCALE / 2, rect.width,
                                                     TITLE_FONT_SIZE * FONT_SCALE))

  def render_download_failed(self, rect: rl.Rectangle):
    self._download_failed_title_label.render(rl.Rectangle(rect.x + 117, rect.y + 185, rect.width - 117, TITLE_FONT_SIZE * FONT_SCALE))
    self._download_failed_url_label.set_text(self.failed_url)
    self._download_failed_url_label.render(rl.Rectangle(rect.x + 117, rect.y + 185 + TITLE_FONT_SIZE * FONT_SCALE + 67, rect.width - 117 - 100, 64))

    self._download_failed_body_label.set_text(self.failed_reason)
    self._download_failed_body_label.render(rl.Rectangle(rect.x + 117, rect.y, rect.width - 117 - 100, rect.height))

    button_width = (rect.width - BUTTON_SPACING - MARGIN * 2) / 2
    button_y = rect.height - BUTTON_HEIGHT - MARGIN
    self._download_failed_reboot_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._download_failed_startover_button.render(rl.Rectangle(rect.x + MARGIN + button_width + BUTTON_SPACING, button_y, button_width, BUTTON_HEIGHT))

  def render_custom_software_warning(self, rect: rl.Rectangle):
    warn_rect = rl.Rectangle(rect.x, rect.y, rect.width, 1550)
    offset = self._custom_software_warning_body_scroll_panel.update(rect, warn_rect)

    button_width = (rect.width - MARGIN * 3) / 2
    button_y = rect.height - MARGIN - BUTTON_HEIGHT

    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(button_y - BODY_FONT_SIZE * FONT_SCALE))
    y_offset = rect.y + offset
    self._custom_software_warning_title_label.render(rl.Rectangle(rect.x + 50, y_offset + 150, rect.width - 265, TITLE_FONT_SIZE * FONT_SCALE))

    y = y_offset + 300
    for label in self._custom_software_warning_body_labels:
      label.render(rl.Rectangle(rect.x + 50,  y, rect.width - 50, BODY_FONT_SIZE))
      y += 160

    rl.end_scissor_mode()

    self._custom_software_warning_back_button.render(rl.Rectangle(rect.x + MARGIN, button_y, button_width, BUTTON_HEIGHT))
    self._custom_software_warning_continue_button.render(rl.Rectangle(rect.x + MARGIN * 2 + button_width, button_y, button_width, BUTTON_HEIGHT))
    if offset < (rect.height - warn_rect.height):
      self._custom_software_warning_continue_button.set_enabled(True)
      self._custom_software_warning_continue_button.set_text(tr("Continue"))

  def render_custom_software(self):
    def handle_keyboard_result(result):
      # Enter pressed
      if result == DialogResult.CONFIRM:
        url = self.keyboard.text
        self.keyboard.clear()
        if url:
          self.download(url)

      # Cancel pressed
      elif result == DialogResult.CANCEL:
        self.state = SetupState.SOFTWARE_SELECTION

    self.keyboard.reset(min_text_size=1)
    self.keyboard.set_title(tr("Enter URL"), tr("owner/branch, owner/repo/branch or git URL"))
    self.keyboard.set_callback(handle_keyboard_result)
    gui_app.push_widget(self.keyboard)

  def download(self, spec: str):
    """Install from git. spec is "owner/branch", "owner/repo/branch" or a full clone URL."""
    self.download_url = spec
    self.download_status = tr("Searching repositories...")
    self.download_progress = 0
    self.state = SetupState.DOWNLOADING
    self.download_thread = threading.Thread(target=self._git_install_thread, args=(spec,), daemon=True)
    self.download_thread.start()

  def _resolve_target(self, spec: str):
    """Return (clone_url, branch); clone_url None means the probe found nothing."""
    if "://" in spec:
      return spec, None
    parts = spec.strip().strip("/").split("/")
    owner_re = r"^[^/.@]+$"  # git host paths never start with a dotted owner
    if len(parts) == 2 and re.match(owner_re, parts[0]):
      # shorthand "owner/branch": probe every host x repo name
      return resolve_git_repo(parts[0], parts[1]), parts[1]
    if len(parts) == 3 and re.match(owner_re, parts[0]):
      # explicit "owner/repo/branch": probe hosts for that repo name only
      return resolve_git_repo(parts[0], parts[2], (parts[1],)), parts[2]
    return (f"https://{spec}" if "://" not in spec else spec), None

  def _git_install_thread(self, spec: str):
    try:
      clone_url, branch = self._resolve_target(spec)
      if clone_url is None:
        self.download_failed(self.download_url, tr("No custom software found at this URL."))
        return
      self.download_url = clone_url
      install_from_git(clone_url, branch,
                       on_status=self._set_git_status,
                       on_progress=lambda pct: setattr(self, 'download_progress', pct))

      # comma.sh only re-checks /data/continue.sh after /tmp/installer shows
      # up and exits: a no-op installer unblocks the boot loop now that
      # continue.sh is already written.
      with open(INSTALLER_DESTINATION_PATH, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
      os.chmod(INSTALLER_DESTINATION_PATH, 0o755)

      # give time for the UI to settle before the app closes
      time.sleep(0.1)
      gui_app.request_close()
    except GitInstallError as e:
      self.download_failed(self.download_url, self._git_error_texts.get(e.kind, tr("Install failed.")))
    except Exception:
      self.download_failed(self.download_url, tr("Ensure the entered URL is valid, and the device's internet connection is good."))

  def _set_git_status(self, key: str):
    self.download_status = self._git_status_texts.get(key, self.download_status)

  def download_failed(self, url: str, reason: str):
    self.failed_url = url
    self.failed_reason = reason
    self.state = SetupState.DOWNLOAD_FAILED


def main():
  try:
    gui_app.init_window("Setup", 20)
    setup = Setup()
    gui_app.push_widget(setup)
    for _ in gui_app.render():
      pass
    setup.close()
  except Exception as e:
    print(f"Setup error: {e}")
  finally:
    gui_app.close()


if __name__ == "__main__":
  main()
