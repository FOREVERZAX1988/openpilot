import os
import math

from cereal import messaging, log
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.onroad.driver_camera_dialog import DriverCameraDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.onboarding import TrainingGuide
from openpilot.selfdrive.ui.widgets.pairing_dialog import PairingDialog
from openpilot.system.hardware import TICI
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import multilang, tr, tr_noop
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.html_render import HtmlModal
from openpilot.system.ui.widgets.list_view import text_item, button_item, dual_button_item
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.scroller_tici import Scroller
#new add
from system.ui.ui_state import ui_state  # 确保导入了ui_state

# 1. 全局定义服务器常量（避免重复声明）
SERVER_KONIK_NAME = "konik"
SERVER_COMMA_NAME = "comma"

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp as button_item

# Description constants
DESCRIPTIONS = {
  'pair_device': tr_noop("Pair your device with comma connect (connect.comma.ai) and claim your comma prime offer."),
  'driver_camera': tr_noop("Preview the driver facing camera to ensure that driver monitoring has good visibility. (vehicle must be off)"),
  'reset_calibration': tr_noop("sunnypilot requires the device to be mounted within 4° left or right and within 5° up or 9° down."),
  'review_guide': tr_noop("Review the rules, features, and limitations of sunnypilot"),
  #第一步（共5）：Add a description to the new server switch button.
  'server_selection': tr_noop("Switch the connected server (Konik or Comma)"),
  'select_server_title': tr_noop("select server"), 
  'konik_server': tr_noop("konik server"),
  'comma_server': tr_noop("comma server"),
}


class DeviceLayout(Widget):
  def __init__(self):
    super().__init__()

    self._params = Params()
    self._select_language_dialog: MultiOptionDialog | None = None
    self._driver_camera: DriverCameraDialog | None = None
    self._pair_device_dialog: PairingDialog | None = None
    self._fcc_dialog: HtmlModal | None = None
    self._training_guide: TrainingGuide | None = None
    self._server_dialog: MultiOptionDialog | None = None  # 第二步（共5）：Add a description to the new server switch button.
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

    ui_state.add_offroad_transition_callback(self._offroad_transition)

  def _initialize_items(self):
    self._pair_device_btn = button_item(lambda: tr("Pair Device"), lambda: tr("PAIR"), lambda: tr(DESCRIPTIONS['pair_device']), callback=self._pair_device)
    self._pair_device_btn.set_visible(lambda: not ui_state.prime_state.is_paired())

    self._reset_calib_btn = button_item(lambda: tr("Reset Calibration"), lambda: tr("RESET"), lambda: tr(DESCRIPTIONS['reset_calibration']),
                                        callback=self._reset_calibration_prompt)
    self._reset_calib_btn.set_description_opened_callback(self._update_calib_description)

    self._power_off_btn = dual_button_item(lambda: tr("Reboot"), lambda: tr("Power Off"),
                                           left_callback=self._reboot_prompt, right_callback=self._power_off_prompt)
    #第三步：Add a server selection button.
    self._server_btn = button_item(
            lambda: tr(DESCRIPTIONS['server_selection']),  # 主标题：Switch Server (Konik/Comma)
            lambda: tr("Current Server: {}").format(self._get_current_server()),  # 副标题：当前服务器
            lambda: tr(DESCRIPTIONS['server_selection']),  # 描述
            callback=self._show_server_dialog,
            enabled=lambda: ui_state.is_offroad  # 延迟判断，避免UI阻塞
        )

    items = [
      text_item(lambda: tr("Dongle ID"), self._params.get("DongleId") or (lambda: tr("N/A"))),
      text_item(lambda: tr("Serial"), self._params.get("HardwareSerial") or (lambda: tr("N/A"))),
      self._pair_device_btn,
      button_item(lambda: tr("Driver Camera"), lambda: tr("PREVIEW"), lambda: tr(DESCRIPTIONS['driver_camera']),
                  callback=self._show_driver_camera, enabled=ui_state.is_offroad),
      self._reset_calib_btn,
      button_item(lambda: tr("Review Training Guide"), lambda: tr("REVIEW"), lambda: tr(DESCRIPTIONS['review_guide']),
                  self._on_review_training_guide, enabled=ui_state.is_offroad),
      regulatory_btn := button_item(lambda: tr("Regulatory"), lambda: tr("VIEW"), callback=self._on_regulatory, enabled=ui_state.is_offroad),
      button_item(lambda: tr("Change Language"), lambda: tr("CHANGE"), callback=self._show_language_dialog),
      # 第四步（共5）：Add a server selection button.
      self._server_btn,  # 添加到项目列表中
      self._power_off_btn,
    ]
    regulatory_btn.set_visible(TICI)
    return items

  def _offroad_transition(self):
    self._power_off_btn.action_item.right_button.set_visible(ui_state.is_offroad())

  def show_event(self):
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)

  def _show_language_dialog(self):
    def handle_language_selection(result: int):
      if result == 1 and self._select_language_dialog:
        selected_language = multilang.languages[self._select_language_dialog.selection]
        multilang.change_language(selected_language)
        self._update_calib_description()
      self._select_language_dialog = None

    self._select_language_dialog = MultiOptionDialog(tr("Select a language"), multilang.languages, multilang.codes[multilang.language],
                                                     option_font_weight=FontWeight.UNIFONT)
    gui_app.set_modal_overlay(self._select_language_dialog, callback=handle_language_selection)

  def _show_driver_camera(self):
    if not self._driver_camera:
      self._driver_camera = DriverCameraDialog()

    gui_app.set_modal_overlay(self._driver_camera, callback=lambda result: setattr(self, '_driver_camera', None))

  def _reset_calibration_prompt(self):
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Reset Calibration")))
      return

    def reset_calibration(result: int):
      # Check engaged again in case it changed while the dialog was open
      if ui_state.engaged or result != DialogResult.CONFIRM:
        return

      self._params.remove("CalibrationParams")
      self._params.remove("LiveTorqueParameters")
      self._params.remove("LiveParameters")
      self._params.remove("LiveParametersV2")
      self._params.remove("LiveDelay")
      self._params.put_bool("OnroadCycleRequested", True)
      self._update_calib_description()

    dialog = ConfirmDialog(tr("Are you sure you want to reset calibration?"), tr("Reset"))
    gui_app.set_modal_overlay(dialog, callback=reset_calibration)

  def _update_calib_description(self):
    desc = tr(DESCRIPTIONS['reset_calibration'])

    calib_bytes = self._params.get("CalibrationParams")
    if calib_bytes:
      try:
        calib = messaging.log_from_bytes(calib_bytes, log.Event).liveCalibration

        if calib.calStatus != log.LiveCalibrationData.Status.uncalibrated:
          pitch = math.degrees(calib.rpyCalib[1])
          yaw = math.degrees(calib.rpyCalib[2])
          desc += tr(" Your device is pointed {:.1f}° {} and {:.1f}° {}.").format(abs(pitch), tr("down") if pitch > 0 else tr("up"),
                                                                                  abs(yaw), tr("left") if yaw > 0 else tr("right"))
      except Exception:
        cloudlog.exception("invalid CalibrationParams")

    lag_perc = 0
    lag_bytes = self._params.get("LiveDelay")
    if lag_bytes:
      try:
        lag_perc = messaging.log_from_bytes(lag_bytes, log.Event).liveDelay.calPerc
      except Exception:
        cloudlog.exception("invalid LiveDelay")
    if lag_perc < 100:
      desc += tr("<br><br>Steering lag calibration is {}% complete.").format(lag_perc)
    else:
      desc += tr("<br><br>Steering lag calibration is complete.")

    torque_bytes = self._params.get("LiveTorqueParameters")
    if torque_bytes:
      try:
        torque = messaging.log_from_bytes(torque_bytes, log.Event).liveTorqueParameters
        # don't add for non-torque cars
        if torque.useParams:
          torque_perc = torque.calPerc
          if torque_perc < 100:
            desc += tr(" Steering torque response calibration is {}% complete.").format(torque_perc)
          else:
            desc += tr(" Steering torque response calibration is complete.")
      except Exception:
        cloudlog.exception("invalid LiveTorqueParameters")

    desc += "<br><br>"
    desc += tr("sunnypilot is continuously calibrating, resetting is rarely required. " +
               "Resetting calibration will restart sunnypilot if the car is powered on.")

    self._reset_calib_btn.set_description(desc)

  def _reboot_prompt(self):
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Reboot")))
      return

    dialog = ConfirmDialog(tr("Are you sure you want to reboot?"), tr("Reboot"))
    gui_app.set_modal_overlay(dialog, callback=self._perform_reboot)

  def _perform_reboot(self, result: int):
    if not ui_state.engaged and result == DialogResult.CONFIRM:
      self._params.put_bool_nonblocking("DoReboot", True)

  def _power_off_prompt(self):
    if ui_state.engaged:
      gui_app.set_modal_overlay(alert_dialog(tr("Disengage to Power Off")))
      return

    dialog = ConfirmDialog(tr("Are you sure you want to power off?"), tr("Power Off"))
    gui_app.set_modal_overlay(dialog, callback=self._perform_power_off)

  def _perform_power_off(self, result: int):
    if not ui_state.engaged and result == DialogResult.CONFIRM:
      self._params.put_bool_nonblocking("DoShutdown", True)

  def _pair_device(self):
    if not self._pair_device_dialog:
      self._pair_device_dialog = PairingDialog()
    gui_app.set_modal_overlay(self._pair_device_dialog, callback=lambda result: setattr(self, '_pair_device_dialog', None))

  def _on_regulatory(self):
    if not self._fcc_dialog:
      self._fcc_dialog = HtmlModal(os.path.join(BASEDIR, "selfdrive/assets/offroad/fcc.html"))
    gui_app.set_modal_overlay(self._fcc_dialog)

  def _on_review_training_guide(self):
    if not self._training_guide:
      def completed_callback():
        gui_app.set_modal_overlay(None)

      self._training_guide = TrainingGuide(completed_callback=completed_callback)
    gui_app.set_modal_overlay(self._training_guide)

# 第五步（共5）：添加服务器切换辅助方法
'''  def _get_current_server(self):
    server_type = self._params.get("ServerType", "konik")
    return "Konik" if server_type == "konik" else "Comma"
'''
  def _get_current_server(self):
      server_type = self._params.get("ServerType", SERVER_KONIK_NAME)
      return SERVER_KONIK_NAME.capitalize() if server_type == SERVER_KONIK_NAME else SERVER_COMMA_NAME.capitalize()

  def _show_server_dialog(self):
      current_server = self._params.get("ServerType", SERVER_KONIK_NAME)

    def handle_server_selection(result: int):
        if result == 1 and self._server_dialog:
            selected = self._server_dialog.selection
            server_type = SERVER_KONIK_NAME if selected == 0 else SERVER_COMMA_NAME
            self._params.put("ServerType", server_type)
            # 提示需要重启
            gui_app.set_modal_overlay(alert_dialog(tr("The server has been switched. The change will take effect after the device is restarted.")))
        self._server_dialog = None

    self._server_dialog = MultiOptionDialog(
        tr(DESCRIPTIONS['select_server_title']),
        [tr(DESCRIPTIONS['konik_server']), tr(DESCRIPTIONS['comma_server'])],
        0 if current_server == SERVER_KONIK_NAME else 1  # 正确判断初始选中项
    )
    gui_app.set_modal_overlay(self._server_dialog, callback=handle_server_selection)