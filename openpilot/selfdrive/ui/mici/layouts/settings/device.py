import os
import pyray as rl
from collections.abc import Callable

from openpilot.common.basedir import BASEDIR
from openpilot.common.api.comma_connect import get_api_host
from openpilot.common.params import Params
from openpilot.common.time_helpers import system_time_valid
from openpilot.system.ui.widgets.scroller import NavRawScrollPanel, NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigCircleButton, BigMultiToggle, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigConfirmationDialog
from openpilot.selfdrive.ui.mici.widgets.pairing_dialog import PairingDialog
from openpilot.selfdrive.ui.mici.onroad.cabin_camera_dialog import CabinCameraDialog
from openpilot.selfdrive.ui.mici.layouts.onboarding import TrainingGuide, TermsPage
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.multilang import tr, multilang
from openpilot.system.ui.widgets import Widget
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.html_render import HtmlRenderer
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID


class ReviewTermsPage(TermsPage, NavScroller):
  """TermsPage with NavWidget swipe-to-dismiss for reviewing in device settings."""
  def __init__(self):
    super().__init__(on_accept=self.dismiss, on_decline=self.dismiss)
    self._terms_header.set_visible(False)
    self._must_accept_card.set_visible(False)
    self._accept_button.set_visible(False)
    self._decline_button.set_visible(False)


class ReviewTrainingGuide(TrainingGuide):
  def show_event(self):
    super().show_event()
    device.set_override_interactive_timeout(300)

  def hide_event(self):
    super().hide_event()
    device.set_override_interactive_timeout(None)
    ui_state.params.put_bool("IsDriverViewEnabled", False)


class MiciFccModal(NavRawScrollPanel):
  def __init__(self, file_path: str | None = None, text: str | None = None):
    super().__init__()
    self._content = HtmlRenderer(file_path=file_path, text=text)
    self._fcc_logo = gui_app.texture("icons_mici/settings/device/fcc_logo.png", 76, 64)

  def _render(self, rect: rl.Rectangle):
    content_height = self._content.get_total_height(int(rect.width))
    content_height += self._fcc_logo.height + 20

    scroll_content_rect = rl.Rectangle(rect.x, rect.y, rect.width, content_height)
    scroll_offset = round(self._scroll_panel.update(rect, scroll_content_rect.height))

    fcc_pos = rl.Vector2(rect.x + 20, rect.y + 20 + scroll_offset)

    scroll_content_rect.y += scroll_offset + self._fcc_logo.height + 20
    self._content.render(scroll_content_rect)

    rl.draw_texture_ex(self._fcc_logo, fcc_pos, 0.0, 1.0, rl.WHITE)


def _engaged_confirmation_click(callback: Callable, action_text: str, icon: rl.Texture, exit_on_confirm: bool = True, red: bool = False):
  if not ui_state.engaged:
    def confirm_callback():
      # Check engaged again in case it changed while the dialog was open
      # TODO: if true, we stay on the dialog if not exit_on_confirm until normal onroad timeout
      if not ui_state.engaged:
        callback()

    gui_app.push_widget(BigConfirmationDialog(tr("slide to\n{}").format(tr(action_text).lower()), icon, confirm_callback, exit_on_confirm=exit_on_confirm, red=red))
  else:
    gui_app.push_widget(BigDialog("", tr("Disengage to {}").format(tr(action_text))))


class EngagedConfirmationCircleButton(BigCircleButton):
  def __init__(self, title: str, icon: rl.Texture, callback: Callable[[], None], exit_on_confirm: bool = True,
               red: bool = False, icon_offset: tuple[int, int] = (0, 0)):
    super().__init__(icon, red, icon_offset)
    self.set_click_callback(lambda: _engaged_confirmation_click(callback, title, icon, exit_on_confirm=exit_on_confirm, red=red))


class EngagedConfirmationButton(BigButton):
  def __init__(self, text: str, action_text: str, icon: rl.Texture, callback: Callable[[], None],
               exit_on_confirm: bool = True, red: bool = False):
    super().__init__(text, "", icon)
    self.set_click_callback(lambda: _engaged_confirmation_click(callback, action_text, icon, exit_on_confirm=exit_on_confirm, red=red))


class DeviceInfoLayoutMici(Widget):
  def __init__(self):
    super().__init__()

    self.set_rect(rl.Rectangle(0, 0, 360, 180))

    params = Params()
    subheader_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    self._dongle_id_label = UnifiedLabel(tr("device ID"), 48, max_width=max_width, font_weight=FontWeight.DISPLAY, wrap_text=False)
    self._dongle_id_text_label = UnifiedLabel(params.get("DongleId") or 'N/A', 32, max_width=max_width, text_color=subheader_color,
                                              font_weight=FontWeight.ROMAN, wrap_text=False)

    self._serial_number_label = UnifiedLabel(tr("serial"), 48, max_width=max_width, font_weight=FontWeight.DISPLAY, wrap_text=False)
    self._serial_number_text_label = UnifiedLabel(params.get("HardwareSerial") or 'N/A', 32, max_width=max_width, text_color=subheader_color,
                                                  font_weight=FontWeight.ROMAN, wrap_text=False)

  def _render(self, _):
    self._dongle_id_label.set_position(self._rect.x + 20, self._rect.y - 10)
    self._dongle_id_label.render()

    self._dongle_id_text_label.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self._dongle_id_text_label.render()

    self._serial_number_label.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self._serial_number_label.render()

    self._serial_number_text_label.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self._serial_number_text_label.render()


class PairBigButton(BigButton):
  def __init__(self):
    super().__init__(tr("pair"), "connect.comma.ai", gui_app.texture("icons_mici/settings/comma_icon.png", 33, 60))

  def _get_label_font_size(self):
    return 64

  def _update_state(self):
    super()._update_state()

    if ui_state.prime_state.is_paired():
      self.set_text(tr("paired"))
      if ui_state.prime_state.is_prime():
        self.set_value(tr("subscribed"))
      else:
        self.set_value(tr("upgrade to prime"))
    else:
      self.set_text("pair")
      self.set_value("connect.comma.ai")

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    # TODO: show ad dialog when clicked if not prime
    if ui_state.prime_state.is_paired():
      return
    dlg: BigDialog | PairingDialog
    if not system_time_valid():
      dlg = BigDialog("", tr(tr("Please connect to Wi-Fi to complete initial pairing.")))
    elif UNREGISTERED_DONGLE_ID == (ui_state.params.get("DongleId") or UNREGISTERED_DONGLE_ID):
      dlg = BigDialog("", tr(tr("Device must be registered with the comma.ai backend to pair.")))
    else:
      dlg = PairingDialog()
    gui_app.push_widget(dlg)


class DeviceLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._fcc_dialog: MiciFccModal | None = None

    def power_off_callback():
      ui_state.params.put_bool("DoShutdown", True, block=True)

    def reboot_callback():
      ui_state.params.put_bool("DoReboot", True, block=True)

    def reset_calibration_callback():
      params = ui_state.params
      params.remove("CalibrationParams")
      params.remove("LiveTorqueParameters")
      params.remove("LiveParametersV2")
      params.remove("LiveDelay")
      params.put_bool("OnroadCycleRequested", True, block=True)

    reset_calibration_btn = EngagedConfirmationButton(tr("reset calibration"), "reset", gui_app.texture("icons_mici/settings/device/lkas.png", 122, 64),
                                                      reset_calibration_callback)

    reboot_btn = EngagedConfirmationCircleButton(tr("reboot"), gui_app.texture("icons_mici/settings/device/reboot.png", 64, 70),
                                                 reboot_callback, exit_on_confirm=False)

    self._power_off_btn = EngagedConfirmationCircleButton(tr("power off"), gui_app.texture("icons_mici/settings/device/power.png", 64, 66),
                                                          power_off_callback, exit_on_confirm=False, red=True)
    self._power_off_btn.set_visible(lambda: not ui_state.ignition)

    # 语言按钮：样式与 driving personality 一致（BigMultiToggle：右上角选项灯+左下角当前值）。
    # 切换后重启 UI 让新语言完整生效：OnroadCycleRequested 不重启 always-on 的 UI 进程，
    # 改 gui_app.request_close() 让 UI 进程退出、由 manager 拉起（2026-08-17 实测修复）。
    self._language_btn = BigMultiToggle(
      tr("language"),
      [multilang.codes.get(c, c) for c in ("en", "zh-CHS")],
      select_callback=self._on_language_selected,
    )
    lang_display = multilang.codes.get(multilang.language, multilang.language)
    if lang_display not in self._language_btn._options:  # 当前语言不在中英选项时默认英文，防 index 崩溃
      lang_display = self._language_btn._options[0]
    self._language_btn.set_value(lang_display)

    # Konik/Comma 服务器显示与切换（与 tizi 的 DeviceLayoutSP 归类一致，2026-08-17）
    self._api_server_btn = GreyBigButton(tr("Current API Server"), get_api_host(),
                                         gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    self._server_btn = BigMultiToggle(
      tr("Server"),
      [tr("COMMA"), tr("KONIK")],
      select_callback=self._on_server_selected,
    )
    self._server_btn.set_value(tr("KONIK") if ui_state.params.get_bool("UseKonikServer", False) else tr("COMMA"))

    regulatory_btn = BigButton(tr("regulatory info"), "", gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    regulatory_btn.set_click_callback(self._on_regulatory)

    cabin_cam_btn = BigButton(tr("driver\ncamera preview"), "", gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64))
    cabin_cam_btn.set_click_callback(lambda: gui_app.push_widget(CabinCameraDialog()))
    cabin_cam_btn.set_enabled(lambda: ui_state.is_offroad())

    review_training_guide_btn = BigButton(tr("review\ntraining guide"), "", gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    review_training_guide_btn.set_click_callback(lambda: gui_app.push_widget(ReviewTrainingGuide(completed_callback=lambda: gui_app.pop_widgets_to(self))))
    review_training_guide_btn.set_enabled(lambda: ui_state.is_offroad())

    terms_btn = BigButton(tr("terms &\nconditions"), "", gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    terms_btn.set_click_callback(lambda: gui_app.push_widget(ReviewTermsPage()))

    self._scroller.add_widgets([
      DeviceInfoLayoutMici(),
      PairBigButton(),
      review_training_guide_btn,
      cabin_cam_btn,
      terms_btn,
      self._language_btn,
      self._api_server_btn,
      self._server_btn,
      regulatory_btn,
      reset_calibration_btn,
      reboot_btn,
      self._power_off_btn,
    ])

  def _on_server_selected(self, value: str):
    """BigMultiToggle 选择回调：COMMA ↔ KONIK 直接切换（样式同驾驶风格）。
    API host 由 athenad 等多进程读取，需整机重启（DoReboot）确保生效（与 tizi 一致）。"""
    use_konik = value == tr("KONIK")
    if use_konik == ui_state.params.get_bool("UseKonikServer", False):
      return
    ui_state.params.put_bool("UseKonikServer", use_konik, block=True)
    ui_state.params.put_bool("DoReboot", True, block=True)

  def _update_state(self):
    super()._update_state()
    # 服务器按钮值跟随 param 刷新（外部修改后同步显示）
    server = tr("KONIK") if ui_state.params.get_bool("UseKonikServer", False) else tr("COMMA")
    self._server_btn.set_value(server)
    self._api_server_btn.set_value(get_api_host())

  def _on_language_selected(self, display_name: str):
    """BigMultiToggle 选择回调：显示名 → 语言代码，切换后重启 UI。
    OnroadCycleRequested 只重启 onroad 循环、不重启 always-on 的 UI 进程（2026-08-17 实测无效），
    改 gui_app.request_close() 让 UI 进程退出、由 manager（managed_processes['ui']）自动拉起，
    新语言完整生效；同时不再调 on_language_changed（会卸载字体导致文字消失/？？）。"""
    new_code = "en"
    for code, name in multilang.codes.items():
      if tr(name) == display_name:
        new_code = code
        break
    if new_code == multilang.language:
      return
    multilang.change_language(new_code)
    gui_app.request_close()

  def _on_regulatory(self):
    if not self._fcc_dialog:
      self._fcc_dialog = MiciFccModal(os.path.join(BASEDIR, "openpilot/selfdrive/assets/offroad/mici_fcc.html"))
    gui_app.push_widget(self._fcc_dialog)
