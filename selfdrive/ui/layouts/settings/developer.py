from openpilot.common.params import Params
from openpilot.selfdrive.ui.widgets.ssh_key import ssh_key_item
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
# 新增依赖：文件操作、路径处理、异常捕获
import os
import shutil

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.hoofpilot.widgets.list_view import toggle_item_sp as toggle_item

# Description constants
DESCRIPTIONS = {
  'enable_adb': tr_noop(
    "ADB (Android Debug Bridge) allows connecting to your device over USB or over the network. " +
    "See https://docs.comma.ai/how-to/connect-to-comma for more info."
  ),
  'ssh_key': tr_noop(
    "Warning: This grants SSH access to all public keys in your GitHub settings. Never enter a GitHub username " +
    "other than your own. A comma employee will NEVER ask you to add their GitHub username."
  ),
  'alpha_longitudinal': tr_noop(
    "<b>WARNING: hoofpilot longitudinal control is in alpha for this car and will disable Automatic Emergency Braking (AEB).</b><br><br>" +
    "On this car, hoofpilot defaults to the car's built-in ACC instead of hoofpilot's longitudinal control. " +
    "Enable this to switch to hoofpilot longitudinal control. " +
    "Enabling Experimental mode is recommended when enabling hoofpilot longitudinal control alpha. " +
    "Changing this setting will restart hoofpilot if the car is powered on."
  ),
  'delete_driving_data': tr_noop(
    "<b>WARNING: This will permanently delete all driving data stored on the device.</b><br><br>" +
    "This includes all logs, realdata, and any other files in the /data/realdata directory. " +
    "This action cannot be undone. Make sure to back up any important data before proceeding."
  ),
}


class DeveloperLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_release = self._params.get_bool("IsReleaseBranch")
    # 新增：定义行驶数据存储路径（根据comma设备实际路径调整）
    self._realdata_path = "/data/media/0/realdata"  # comma设备realdata默认路径

    # Build items and keep references for callbacks/state updates
    self._adb_toggle = toggle_item(
      lambda: tr("Enable ADB"),
      description=lambda: tr(DESCRIPTIONS["enable_adb"]),
      initial_state=self._params.get_bool("AdbEnabled"),
      callback=self._on_enable_adb,
      enabled=ui_state.is_offroad,
    )

    # SSH enable toggle + SSH key management
    self._ssh_toggle = toggle_item(
      lambda: tr("Enable SSH"),
      description="",
      initial_state=self._params.get_bool("SshEnabled"),
      callback=self._on_enable_ssh,
    )
    self._ssh_keys = ssh_key_item(lambda: tr("SSH Keys"), description=lambda: tr(DESCRIPTIONS["ssh_key"]))

    self._joystick_toggle = toggle_item(
      lambda: tr("Joystick Debug Mode"),
      description="",
      initial_state=self._params.get_bool("JoystickDebugMode"),
      callback=self._on_joystick_debug_mode,
      enabled=ui_state.is_offroad,
    )

    self._long_maneuver_toggle = toggle_item(
      lambda: tr("Longitudinal Maneuver Mode"),
      description="",
      initial_state=self._params.get_bool("LongitudinalManeuverMode"),
      callback=self._on_long_maneuver_mode,
    )

    self._alpha_long_toggle = toggle_item(
      lambda: tr("hoofpilot Longitudinal Control (Alpha)"),
      description=lambda: tr(DESCRIPTIONS["alpha_longitudinal"]),
      initial_state=self._params.get_bool("AlphaLongitudinalEnabled"),
      callback=self._on_alpha_long_enabled,
      enabled=lambda: not ui_state.engaged,
    )

    self._ui_debug_toggle = toggle_item(
      lambda: tr("UI Debug Mode"),
      description="",
      initial_state=self._params.get_bool("ShowDebugInfo"),
      callback=self._on_enable_ui_debug,
    )
    self._on_enable_ui_debug(self._params.get_bool("ShowDebugInfo"))

    # 新增：删除行驶数据按钮（复用toggle_item改为按钮逻辑，仅保留点击回调）
    self._delete_data_btn = toggle_item(
      lambda: tr("Delete Driving Data"),
      description=lambda: tr(DESCRIPTIONS["delete_driving_data"]),
      initial_state=False,  # 仅作为按钮，初始状态无意义
      callback=self._on_delete_driving_data,
      enabled=ui_state.is_offroad,  # 仅离线时可操作（防止行车中误删）
    )

    self._scroller = Scroller([
      self._adb_toggle,
      self._ssh_toggle,
      self._ssh_keys,
      self._joystick_toggle,
      self._long_maneuver_toggle,
      self._alpha_long_toggle,
      self._ui_debug_toggle,
      self._delete_data_btn,  # 添加删除数据按钮到滚动列表
    ], line_separator=True, spacing=0)

    # Toggles should be not available to change in onroad state
    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # Hide non-release toggles on release builds
    # TODO: we can do an onroad cycle, but alpha long toggle requires a deinit function to re-enable radar and not fault
    for item in (self._joystick_toggle, self._long_maneuver_toggle, self._alpha_long_toggle):
      item.set_visible(not self._is_release)

    # CP gating
    if ui_state.CP is not None:
      alpha_avail = ui_state.CP.alphaLongitudinalAvailable
      if not alpha_avail or self._is_release:
        self._alpha_long_toggle.set_visible(False)
        self._params.remove("AlphaLongitudinalEnabled")
      else:
        self._alpha_long_toggle.set_visible(True)

      long_man_enabled = ui_state.has_longitudinal_control and ui_state.is_offroad()
      self._long_maneuver_toggle.action_item.set_enabled(long_man_enabled)
      if not long_man_enabled:
        self._long_maneuver_toggle.action_item.set_state(False)
        self._params.put_bool("LongitudinalManeuverMode", False)
    else:
      self._long_maneuver_toggle.action_item.set_enabled(False)
      self._alpha_long_toggle.set_visible(False)
    # 刷新删除按钮状态（仅离线时可用）
    self._delete_data_btn.action_item.set_enabled(ui_state.is_offroad)

    # TODO: make a param control list item so we don't need to manage internal state as much here
    # refresh toggles from params to mirror external changes
    for key, item in (
      ("AdbEnabled", self._adb_toggle),
      ("SshEnabled", self._ssh_toggle),
      ("JoystickDebugMode", self._joystick_toggle),
      ("LongitudinalManeuverMode", self._long_maneuver_toggle),
      ("AlphaLongitudinalEnabled", self._alpha_long_toggle),
      ("ShowDebugInfo", self._ui_debug_toggle),
    ):
      item.action_item.set_state(self._params.get_bool(key))

  def _on_enable_ui_debug(self, state: bool):
    self._params.put_bool("ShowDebugInfo", state)
    gui_app.set_show_touches(state)
    gui_app.set_show_fps(state)
    gui_app.set_show_mouse_coords(state)

  def _on_enable_adb(self, state: bool):
    self._params.put_bool("AdbEnabled", state)

  def _on_enable_ssh(self, state: bool):
    self._params.put_bool("SshEnabled", state)

  def _on_joystick_debug_mode(self, state: bool):
    self._params.put_bool("JoystickDebugMode", state)
    self._params.put_bool("LongitudinalManeuverMode", False)
    self._long_maneuver_toggle.action_item.set_state(False)

  def _on_long_maneuver_mode(self, state: bool):
    self._params.put_bool("LongitudinalManeuverMode", state)
    self._params.put_bool("JoystickDebugMode", False)
    self._joystick_toggle.action_item.set_state(False)

  def _on_alpha_long_enabled(self, state: bool):
    if state:
      def confirm_callback(result: int):
        if result == DialogResult.CONFIRM:
          self._params.put_bool("AlphaLongitudinalEnabled", True)
          self._params.put_bool("OnroadCycleRequested", True)
          self._update_toggles()
        else:
          self._alpha_long_toggle.action_item.set_state(False)

      # show confirmation dialog
      content = (f"<h1>{self._alpha_long_toggle.title}</h1><br>" +
                 f"<p>{self._alpha_long_toggle.description}</p>")

      dlg = ConfirmDialog(content, tr("Enable"), rich=True)
      gui_app.set_modal_overlay(dlg, callback=confirm_callback)

    else:
      self._params.put_bool("AlphaLongitudinalEnabled", False)
      self._params.put_bool("OnroadCycleRequested", True)
      self._update_toggles()

  # 新增：删除行驶数据核心逻辑
  def _delete_realdata_files(self):
    """递归删除realdata目录下所有文件/文件夹"""
    if not os.path.exists(self._realdata_path):
      return  # 路径不存在，无需处理

    # 遍历目录并删除所有内容
    for item in os.listdir(self._realdata_path):
      item_path = os.path.join(self._realdata_path, item)
      try:
        if os.path.isfile(item_path) or os.path.islink(item_path):
          os.unlink(item_path)  # 删除文件/软链接
        elif os.path.isdir(item_path):
          shutil.rmtree(item_path)  # 删除文件夹
      except Exception as e:
        print(f"Failed to delete {item_path}: {e}")  # 打印异常（可根据需要改为弹窗提示）

  # 新增：删除数据按钮点击回调
  def _on_delete_driving_data(self, state: bool):
    # 重置按钮状态（仅作为按钮使用，无需保持开启状态）
    self._delete_data_btn.action_item.set_state(False)

    # 确认弹窗回调
    def confirm_delete(result: int):
      if result == DialogResult.CONFIRM:
        # 确认删除：执行文件删除逻辑
        self._delete_realdata_files()
        # 可选：删除后弹出提示（如需可视化反馈可添加）
        success_dlg = ConfirmDialog(
          tr("Driving data deleted successfully!"),
          tr("OK"),
          rich=True
        )
        gui_app.set_modal_overlay(success_dlg, callback=lambda _: None)

    # 显示删除确认弹窗
    confirm_content = (
      f"<h1>{tr('Confirm Delete')}</h1><br>" +
      f"<p><b>{tr('WARNING: This action cannot be undone!')}</b></p><br>" +
      f"<p>{tr('Are you sure you want to delete all driving data? This will remove all files in:')}</p>" +
      f"<p>{self._realdata_path}</p>"
    )
    confirm_dlg = ConfirmDialog(
      confirm_content,
      tr("Delete"),
      cancel_text=tr("Cancel"),
      rich=True
    )
    gui_app.set_modal_overlay(confirm_dlg, callback=confirm_delete)