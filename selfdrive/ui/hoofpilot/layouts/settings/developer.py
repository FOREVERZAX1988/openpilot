"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import datetime
import os
import shutil  # 新增：导入shutil依赖，用于删除文件夹
from pathlib import Path

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.settings.developer import DeveloperLayout
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import button_item

from openpilot.system.ui.hoofpilot.widgets.html_render import HtmlModalSP
from openpilot.system.ui.hoofpilot.widgets.list_view import toggle_item_sp

PREBUILT_PATH = os.path.join(Paths.comma_home(), "prebuilt") if PC else "/data/openpilot/prebuilt"
REALDATA_PATH = "/data/media/0/realdata"  # 行车数据目录

class DeveloperLayoutSP(DeveloperLayout):
  def __init__(self):
    super().__init__()
    self.error_log_path = os.path.join(Paths.crash_log_root(), "error.log")
    self._is_release_branch: bool = self._is_release or ui_state.params.get_bool("IsReleaseSpBranch")
    self._is_development_branch: bool = ui_state.params.get_bool("IsTestedBranch") or ui_state.params.get_bool("IsDevelopmentBranch")
    self._initialize_items()

    for item in self.items:
      self._scroller.add_widget(item)

  def _initialize_items(self):
    self.show_advanced_controls = toggle_item_sp(tr("Show Advanced Controls"),
                                                 tr("Toggle visibility of advanced hoofpilot controls.<br>This only changes the visibility of the toggles; " +
                                                    "it does not change the actual enabled/disabled state."), param="ShowAdvancedControls")

    self.enable_github_runner_toggle = toggle_item_sp(tr("GitHub Runner Service"), tr("Enables or disables the GitHub runner service."),
                                                      param="EnableGithubRunner")

    self.enable_copyparty_toggle = toggle_item_sp(tr("copyparty Service"),
                                                  tr("copyparty is a very capable file server, you can use it to download your routes, view your logs " +
                                                     "and even make some edits on some files from your browser. " +
                                                     "Requires you to connect to your comma locally via its IP address."), param="EnableCopyparty")

    self.prebuilt_toggle = toggle_item_sp(tr("Quickboot Mode"), "", param="QuickBootToggle", callback=self._on_prebuilt_toggled)

    # 新增：删除行车数据按钮
    self.delete_realdata_btn = button_item(tr("Delete Driving Data"), tr("DELETE"), 
                                           tr("Delete all files in the realdata directory (/data/media/0/realdata)."), 
                                           callback=self._on_delete_realdata_clicked)

    self.error_log_btn = button_item(tr("Error Log"), tr("VIEW"), tr("View the error log for hoofpilot crashes."), callback=self._on_error_log_clicked)

    self.items: list = [self.show_advanced_controls, self.enable_github_runner_toggle, self.enable_copyparty_toggle, self.prebuilt_toggle, self.delete_realdata_btn, self.error_log_btn,]

  @staticmethod
  def _on_prebuilt_toggled(state):
    if state:
      Path(PREBUILT_PATH).touch(exist_ok=True)
    else:
      os.remove(PREBUILT_PATH)
    ui_state.params.put_bool("QuickBootToggle", state)

  def _on_delete_confirm(self, result):
    if result == DialogResult.CONFIRM:
      if os.path.exists(self.error_log_path):
        os.remove(self.error_log_path)

  def _on_error_log_closed(self, result, log_exists):
    if result == DialogResult.CONFIRM and log_exists:
      dialog2 = ConfirmDialog(tr("Would you like to delete this log?"), tr("Yes"), tr("No"), rich=False)
      gui_app.set_modal_overlay(dialog2, callback=self._on_delete_confirm)

  def _on_error_log_clicked(self):
    text = ""
    if os.path.exists(self.error_log_path):
      text = f"<b>{datetime.datetime.fromtimestamp(os.path.getmtime(self.error_log_path)).strftime('%d-%b-%Y %H:%M:%S').upper()}</b><br><br>"
      try:
        with open(self.error_log_path) as file:
          text += file.read()
      except Exception:
        pass
    dialog = HtmlModalSP(text=text, callback=lambda result: self._on_error_log_closed(result, os.path.exists(self.error_log_path)))
    gui_app.set_modal_overlay(dialog)

  # 新增：删除行车数据确认回调
  def _on_delete_realdata_confirm(self, result):
    if result == DialogResult.CONFIRM:
      if os.path.exists(REALDATA_PATH):
        # 遍历目录并删除所有文件/子目录
        for filename in os.listdir(REALDATA_PATH):
          file_path = os.path.join(REALDATA_PATH, filename)
          try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
              os.unlink(file_path)
            elif os.path.isdir(file_path):
              shutil.rmtree(file_path)
          except Exception as e:
            # 捕获异常，避免删除失败导致程序崩溃
            print(f"Failed to delete {file_path}: {e}")
        success_dialog = HtmlModalSP(text=tr("All driving data has been deleted successfully!"), 
                                     title=tr("Delete Complete"))
        gui_app.set_modal_overlay(success_dialog)
  
  # 新增：点击删除行车数据按钮的处理逻辑
  def _on_delete_realdata_clicked(self):
    # 先检查目录是否存在
    if os.path.exists(REALDATA_PATH):
      # 显示确认删除对话框
      dialog = ConfirmDialog(
        tr("Are you sure you want to delete ALL driving data?"),  # 唯一的文本参数
        tr("Delete"),  # 确认按钮文本
        tr("Cancel"),  # 取消按钮文本
        rich=False     # 格式参数（和错误日志一致）
      )
      gui_app.set_modal_overlay(dialog, callback=self._on_delete_realdata_confirm)
    else:
      # 目录不存在时显示提示
      dialog = HtmlModalSP(text=tr("Driving data directory does not exist or is empty."), 
                           title=tr("Delete Driving Data"))
      gui_app.set_modal_overlay(dialog)

  def _update_state(self):
    disable_updates = ui_state.params.get_bool("DisableUpdates")
    show_advanced = ui_state.params.get_bool("ShowAdvancedControls")

    if (prebuilt_file := os.path.exists(PREBUILT_PATH)) != ui_state.params.get_bool("QuickBootToggle"):
      ui_state.params.put_bool("QuickBootToggle", prebuilt_file)
      self.prebuilt_toggle.action_item.set_state(prebuilt_file)

    self.prebuilt_toggle.set_visible(show_advanced and not (self._is_release_branch or self._is_development_branch))
    self.prebuilt_toggle.action_item.set_enabled(disable_updates)

    if disable_updates:
      self.prebuilt_toggle.set_description(tr("When toggled on, this creates a prebuilt file to allow accelerated boot times. When toggled off, it " +
                                              "removes the prebuilt file so compilation of locally edited cpp files can be made."))
    else:
      self.prebuilt_toggle.set_description(tr("Quickboot mode requires updates to be disabled.<br>Enable 'Disable Updates' in the Software panel first."))

    self.enable_copyparty_toggle.set_visible(show_advanced)
    self.enable_github_runner_toggle.set_visible(show_advanced and not self._is_release_branch)
    self.error_log_btn.set_visible(not self._is_release_branch)
    # 新增：控制删除行车数据按钮的可见性（与错误日志按钮保持一致）
    self.delete_realdata_btn.set_visible(not self._is_release_branch)
