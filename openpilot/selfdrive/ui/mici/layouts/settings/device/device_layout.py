import math
import os
import raylib_nb as rl
from collections.abc import Callable
from typing import Union

from openpilot.cereal import log, messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.mici.layouts.settings.device.prime import PrimeScroller
from openpilot.system.ui.widgets.scroller import NavRawScrollPanel, NavScroller
from openpilot.selfdrive.ui.mici.widgets.info import InfoLayoutMici
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigCircleButton, BigToggle, BigParamControl, BigMultiParamToggle
from openpilot.selfdrive.ui.sunnypilot.mici.widgets.button import BigParamOption
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigConfirmationDialog, SettingDescriptionDialog
from openpilot.selfdrive.ui.mici.onroad.cabin_camera_dialog import CabinCameraDialog
from openpilot.selfdrive.ui.mici.layouts.onboarding import TrainingGuide, TermsPage
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.sunnypilot.ui_state import set_always_offroad
from openpilot.system.ui.lib.application import gui_app, MousePos
from openpilot.system.ui.lib.multilang import multilang, tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.widgets.html_render import HtmlRenderer
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID

# minutes the device may sit offroad before it shuts itself down (device.py offroad_time_options)
MAX_TIME_OFFROAD_OPTIONS = {0: 0, 1: 5, 2: 10, 3: 15, 4: 30, 5: 60, 6: 120, 7: 180, 8: 300, 9: 600, 10: 1440, 11: 1800}


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
    self._update_toggles()
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

    gui_app.push_widget(BigConfirmationDialog(tr("slide to\n{}").format(action_text.lower()), icon, confirm_callback,
                                              exit_on_confirm=exit_on_confirm, red=red))
  else:
    gui_app.push_widget(BigDialog("", tr("Disengage to {}").format(action_text)))


class EngagedConfirmationCircleButton(BigCircleButton):
  def __init__(self, title: str, icon: rl.Texture, callback: Callable[[], None], exit_on_confirm: bool = True,
               red: bool = False, icon_offset: tuple[int, int] = (0, 0), *, description: str = ""):
    super().__init__(icon, red, icon_offset, description=description, title=title)
    self.set_click_callback(lambda: _engaged_confirmation_click(callback, title, icon, exit_on_confirm=exit_on_confirm, red=red))


class EngagedConfirmationButton(BigButton):
  def __init__(self, text: str, action_text: str, icon: rl.Texture, callback: Callable[[], None],
               exit_on_confirm: bool = True, red: bool = False, *, description: str = "",
               description_icon: Union[rl.Texture, None] = None):
    super().__init__(text, "", icon, description=description, description_icon=description_icon)
    self.set_click_callback(lambda: _engaged_confirmation_click(callback, action_text, icon, exit_on_confirm=exit_on_confirm, red=red))


class DeviceInfoLayoutMici(InfoLayoutMici):
  # matches Big GUI sidebar Colors.DANGER for thermal state coloring
  THERMAL_DANGER_COLOR = rl.Color(201, 34, 49, 255)

  def __init__(self):
    params = Params()
    super().__init__(tr("device ID"), params.get("DongleId") or tr('N/A'), tr("serial"), params.get("HardwareSerial") or tr('N/A'),
                     title3=tr("temperature"), width=380)

  def _update_state(self):
    super()._update_state()

    # CPU temperature row, mirroring Big GUI sidebar _update_temperature_status:
    # show the live reading when the sensor reports, otherwise GOOD/HIGH; non-ok thermal turns red
    sm = ui_state.sm
    if not sm.updated['deviceState']:
      return
    device_state = sm['deviceState']
    thermal_ok = device_state.thermalStatus == log.DeviceState.ThermalStatus.ok
    cpu_temp_c = device_state.cpuTempC
    temp = cpu_temp_c[0] if len(cpu_temp_c) else 0.0
    if temp > 0:
      text = f"{round(temp)}°C"
    else:
      text = tr("GOOD") if thermal_ok else tr("HIGH")
    color = self._subheader_color if thermal_ok else self.THERMAL_DANGER_COLOR
    self.set_subtext3(text, color)


class PairBigButton(BigButton):
  def __init__(self):
    self._commacare_badge = gui_app.texture("icons_mici/settings/device/commacare.png", 27, 32)
    self._show_commacare = False
    self._comma_icon = gui_app.texture("icons_mici/settings/comma_icon.png", 33, 60)
    self._provider_icons = {provider: gui_app.texture(f"icons_mici/settings/device/paired_{provider}.png", 64, 64)
                           for provider in ("github", "google", "apple")}
    super().__init__(tr("pair to connect"), tr("connect.comma.ai"), self._comma_icon)

  def _update_state(self):
    super()._update_state()

    self._show_commacare = (ui_state.prime_state.is_paired() and ui_state.prime_state.is_prime()
                            and ui_state.prime_state.has_commacare())
    if ui_state.prime_state.is_paired():
      self.set_icon(self._provider_icons.get(ui_state.prime_state.get_pairing_provider(), self._comma_icon))
      self.set_text(tr("paired"))
      if ui_state.prime_state.is_prime():
        self.set_value(tr("prime") if ui_state.prime_state.is_full_prime() else tr("prime lite"))
      else:
        self.set_value(tr("claim prime trial") if ui_state.prime_state.can_claim_prime_trial() else tr("upgrade to prime"))
    else:
      self.set_icon(self._comma_icon)
      self.set_text(tr("pair to connect"))
      self.set_value(tr("connect.comma.ai"))

  def _draw_subtitle(self, rect: rl.Rectangle):
    if self._show_commacare:
      y = rect.y + rect.height - self._commacare_badge.height
      rl.draw_texture_v(self._commacare_badge, rl.Vector2(rect.x, y), rl.WHITE)
      offset = self._commacare_badge.width + 14
      rect = rl.Rectangle(rect.x + offset, rect.y, rect.width - offset, rect.height)
    super()._draw_subtitle(rect)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)

    dlg: BigDialog | PrimeScroller
    if not system_time_valid():
      dlg = BigDialog("", tr("Please connect to Wi-Fi to complete initial pairing."))
    elif UNREGISTERED_DONGLE_ID == (ui_state.params.get("DongleId") or UNREGISTERED_DONGLE_ID):
      dlg = BigDialog("", tr("Device must be registered with the comma.ai backend to pair."))
    else:
      dlg = PrimeScroller()
    gui_app.push_widget(dlg)


class DeviceLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._fcc_dialog: MiciFccModal | None = None
    self._pairing_button = PairBigButton()
    self._pending_pairing_grow_animation = False
    self._preview_callback: Callable | None = None

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
      self._update_calib_description()

    self._reset_calib_btn = EngagedConfirmationButton(tr("reset calibration"), tr("reset"), gui_app.texture("icons_mici/settings/device/lkas.png", 122, 64),
                                                      reset_calibration_callback,
                                                      description=self._calib_base_description())
    self._update_calib_description()

    reboot_btn = EngagedConfirmationCircleButton(tr("reboot"), gui_app.texture("icons_mici/settings/device/reboot.png", 64, 70),
                                                 reboot_callback, exit_on_confirm=False)

    self._power_off_btn = EngagedConfirmationCircleButton(tr("power off"), gui_app.texture("icons_mici/settings/device/power.png", 64, 66),
                                                          power_off_callback, exit_on_confirm=False, red=True)
    # Big GUI shows Power Off only when parked (offroad), not merely ignition-off.
    self._power_off_btn.set_visible(lambda: ui_state.is_offroad())

    self._metric_toggle = BigToggle(tr("use metric units"), initial_state=ui_state.params.get_bool("IsMetric"), toggle_callback=self._on_metric_toggle)

    def _max_time_offroad_label(value):
      if not value:
        return tr("always on")
      label = tr("{} m").format(value) if value < 60 else tr("{} h").format(value // 60)
      if value == 1800:
        label += "\n" + tr("(default)")
      return label

    language_btn = BigButton(tr("change\nlanguage"), tr("change"), gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    language_btn.set_click_callback(self._on_change_language)

    self._wake_mode_toggle = BigMultiParamToggle(tr("wake up behavior"), "DeviceBootMode", [tr("default"), tr("offroad")],
                                                 description=tr("Controls the state of the device after boot or sleep.\n" +
                                                                "Offroad keeps the device in always offroad mode after booting or waking up."))
    self._max_time_offroad = BigParamOption(tr("max time offroad"), "MaxTimeOffroad",
                                            min_value=0, max_value=11, value_map=MAX_TIME_OFFROAD_OPTIONS,
                                            label_callback=_max_time_offroad_label,
                                            description=tr("The device shuts down automatically this long after the engine is turned off.\n" +
                                                           "30 h is the default."))
    self._quiet_mode_toggle = BigParamControl(tr("quiet mode"), "QuietMode",
                                              description=tr("Silences the chimes and prompts openpilot plays while offroad."))
    self._onroad_uploads_toggle = BigParamControl(tr("onroad uploads"), "OnroadUploads",
                                                  description=tr("Uploads data while driving. Without it, uploads wait until the car is off."))

    reset_settings_btn = BigButton(tr("reset\nsettings"), tr("erase"), gui_app.texture("icons_mici/settings/device/reboot.png", 64, 70),
                                   description=tr("Resets every setting to its default, then reboots the device."))
    reset_settings_btn.set_click_callback(self._on_reset_settings)
    reset_settings_btn.set_enabled(lambda: ui_state.is_offroad())

    self._safe_mode_btn = BigButton(tr("safe mode"), tr("off"), gui_app.texture("icons_mici/setup/warning.png", 64, 64),
                                    description=tr("Switches every driving knob this fork adds to a conservative value and remembers what it replaced.\n" +
                                                   "Undo puts the learned values back. Parked only."))
    self._safe_mode_btn.set_click_callback(self._on_safe_mode)
    self._safe_mode_btn.set_enabled(lambda: ui_state.is_offroad())

    self._always_offroad_btn = BigButton(tr("always\noffroad"), "", gui_app.texture("icons_mici/settings/device/power.png", 64, 66),
                                         description=tr("Keeps openpilot off the road even after a reboot. hardwared applies it when the car is ready."))
    self._always_offroad_btn.set_click_callback(self._on_always_offroad)

    record_front = BigParamControl(tr("record & upload cabin camera"), "RecordFront",
                                   description_icon=gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64),
                                   toggle_callback=restart_needed_callback, description=tr("Upload cabin camera data to help improve driver monitoring."))
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic = BigParamControl(tr("record & upload mic audio"), "RecordAudio", description_icon=gui_app.texture("icons_mici/microphone.png", 64, 64),
                                 toggle_callback=restart_needed_callback,
                                 description=tr("Record microphone audio while driving.\n" +
                                                "Audio is included in dashcam videos in sunnylink."))
    record_mic.set_enabled(lambda: not ui_state.engaged)
    self._param_toggles = (("RecordFront", record_front), ("RecordAudio", record_mic))

    regulatory_btn = BigButton(tr("regulatory info"), "", gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    regulatory_btn.set_click_callback(self._on_regulatory)
    # Big GUI gates Regulatory behind offroad as well.
    regulatory_btn.set_enabled(lambda: ui_state.is_offroad())

    cabin_cam_btn = BigButton(tr("driver\ncamera preview"), "", gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64),
                              description=tr("Preview the cabin camera to check driver monitoring visibility. The vehicle must be off."))
    cabin_cam_btn.set_click_callback(lambda: gui_app.push_widget(CabinCameraDialog()))
    cabin_cam_btn.set_enabled(lambda: ui_state.is_offroad())

    self._onroad_preview_btn = BigButton(tr("onroad\npreview"), "", gui_app.texture("icons_mici/settings/device/cameras.png", 64, 64))
    self._onroad_preview_btn.set_click_callback(self._enter_onroad_preview)
    self._onroad_preview_btn.set_enabled(lambda: ui_state.is_offroad() or ui_state.params.get_bool("IsOnroadPreview"))

    review_training_guide_btn = BigButton(tr("review\ntraining guide"), "", gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    review_training_guide_btn.set_click_callback(lambda: gui_app.push_widget(ReviewTrainingGuide(completed_callback=lambda: gui_app.pop_widgets_to(self))))
    review_training_guide_btn.set_enabled(lambda: ui_state.is_offroad())

    terms_btn = BigButton(tr("terms &\nconditions"), "", gui_app.texture("icons_mici/settings/device/info.png", 64, 64))
    terms_btn.set_click_callback(lambda: gui_app.push_widget(ReviewTermsPage()))

    self._scroller.add_widgets([
      DeviceInfoLayoutMici(),
      self._pairing_button,
      self._metric_toggle,
      language_btn,
      self._wake_mode_toggle,
      self._max_time_offroad,
      self._quiet_mode_toggle,
      self._onroad_uploads_toggle,
      record_front,
      record_mic,
      review_training_guide_btn,
      cabin_cam_btn,
      self._onroad_preview_btn,
      terms_btn,
      regulatory_btn,
      self._reset_calib_btn,
      self._safe_mode_btn,
      self._always_offroad_btn,
      reset_settings_btn,
      reboot_btn,
      self._power_off_btn,
    ])

    ui_state.add_engaged_transition_callback(self._update_toggles)

  @staticmethod
  def _calib_base_description() -> str:
    return tr("Mount the device within 4° left or right and 5° up or 9° down. openpilot calibrates " +
              "continuously; resetting is rarely needed. Resetting clears learned calibration.")

  def _update_calib_description(self):
    # live calibration facts appended to the reset calibration description,
    # mirroring Big GUI layouts/settings/device.py _update_calib_description
    desc = self._calib_base_description()
    params = ui_state.params

    calib_bytes = params.get("CalibrationParams")
    if calib_bytes:
      try:
        calib = messaging.log_from_bytes(calib_bytes, log.Event).extrinsicsCalibration
        if calib.calStatus != log.ExtrinsicsCalibration.Status.uncalibrated:
          pitch = math.degrees(calib.rpyCalib[1])
          yaw = math.degrees(calib.rpyCalib[2])
          desc += "\n" + tr("Device is pointed {:.1f}° {} and {:.1f}° {}.").format(
            abs(pitch), tr("down") if pitch > 0 else tr("up"),
            abs(yaw), tr("left") if yaw > 0 else tr("right"))
      except Exception:
        cloudlog.exception("invalid CalibrationParams")

    lag_perc = 0
    lag_bytes = params.get("LiveDelay")
    if lag_bytes:
      try:
        lag_perc = messaging.log_from_bytes(lag_bytes, log.Event).lateralDelay.calPerc
      except Exception:
        cloudlog.exception("invalid LiveDelay")
    if lag_perc < 100:
      desc += "\n" + tr("Steering lag calibration is {}% complete.").format(lag_perc)
    else:
      desc += "\n" + tr("Steering lag calibration is complete.")

    torque_bytes = params.get("LiveTorqueParameters")
    if torque_bytes:
      try:
        torque = messaging.log_from_bytes(torque_bytes, log.Event).lateralTorqueParameters
        # don't add for non-torque cars
        if torque.useParams:
          if torque.calPerc < 100:
            desc += "\n" + tr("Steering torque response calibration is {}% complete.").format(torque.calPerc)
          else:
            desc += "\n" + tr("Steering torque response calibration is complete.")
      except Exception:
        cloudlog.exception("invalid LiveTorqueParameters")

    icon = gui_app.texture("icons_mici/settings/device/lkas.png", 122, 64)
    self._reset_calib_btn.set_long_press_callback(
      lambda: gui_app.push_widget(SettingDescriptionDialog(tr("reset calibration"), desc, icon)))

  def _on_metric_toggle(self, state: bool):
    ui_state.params.put_bool("IsMetric", state, block=True)
    ui_state.update_params()

  def _on_change_language(self):
    self._select_language_dialog = MultiOptionDialog(tr("Select a language"), list(multilang.languages),
                                                     multilang.codes[multilang.language],
                                                     callback=self._handle_language_selection)
    gui_app.push_widget(self._select_language_dialog)

  def _handle_language_selection(self, result: DialogResult):
    if result == DialogResult.CONFIRM and self._select_language_dialog:
      selected_language = multilang.languages[self._select_language_dialog.selection]
      multilang.change_language(selected_language)
      gui_app.on_language_changed(selected_language)
    self._select_language_dialog = None

  def _on_safe_mode(self):
    """Switch Safe Mode on or off through the guarded transition.

    The decision is not made here: safe_mode_runtime owns the gate, so the
    button cannot disagree with the API about when the change is allowed.
    """
    from openpilot.sunnypilot.common.safe_mode_runtime import SafeModeError, safe_mode_status, set_safe_mode
    params = ui_state.params
    status = safe_mode_status(params)
    if status["reason"]:
      gui_app.push_widget(BigDialog("", tr(status["reason"])))
      return

    enabling = not status["active"]

    def do_set():
      try:
        new_status = set_safe_mode(params, enabling)
      except SafeModeError as exc:
        gui_app.push_widget(BigDialog("", str(exc)))
        return
      if new_status["active"]:
        gui_app.push_widget(BigDialog("", tr("Safe Mode is on. Reboot so every process picks up the forced values.")))
        self._safe_mode_btn.set_value(tr("on"))

    gui_app.push_widget(BigConfirmationDialog(tr("slide to\n{} safe mode").format(tr("undo") if status["active"] else tr("enable")),
                                              gui_app.texture("icons_mici/setup/warning.png", 64, 64), do_set, red=enabling))

  def _on_always_offroad(self):
    """Big GUI parity: the guarded Always Offroad switch (P0-1).

    Writes OffroadModeRequested only; hardwared owns the actual transition,
    so entering waits until the car hands control back.
    """
    if ui_state.engaged:
      gui_app.push_widget(BigDialog("", tr("Disengage to enter Always Offroad mode")))
      return

    enabling = not ui_state.always_offroad

    def do_set():
      if not ui_state.engaged:
        set_always_offroad(ui_state.params, enabling)

    action = tr("exit") if not enabling else tr("enter")
    gui_app.push_widget(BigConfirmationDialog(tr("slide to\n{} always offroad").format(action),
                                              gui_app.texture("icons_mici/settings/device/power.png", 64, 66),
                                              do_set, red=not enabling))

  def _on_reset_settings(self):
    reset_icon = gui_app.texture("icons_mici/settings/device/reboot.png", 64, 70)

    def do_reset():
      for key in ui_state.params.all_keys():
        ui_state.params.remove(key)
      from openpilot.common.hardware import HARDWARE
      HARDWARE.reboot()

    # Big GUI parity: two-stage confirmation. The first slide arms the flow,
    # the second makes the unrecoverable step explicit (P1-1).
    def second_confirm():
      gui_app.push_widget(BigConfirmationDialog(tr("slide to\nconfirm reset"), reset_icon, do_reset, red=True))

    gui_app.push_widget(BigConfirmationDialog(tr("slide to\nreset settings"), reset_icon, second_confirm, red=True))

  def _update_toggles(self):
    # mirror external param changes
    self._metric_toggle.set_checked(ui_state.params.get_bool("IsMetric"))
    for key, item in self._param_toggles:
      item.set_checked(ui_state.params.get_bool(key))

  def set_preview_callback(self, callback: Callable | None) -> None:
    self._preview_callback = callback

  def _enter_onroad_preview(self) -> None:
    is_preview = ui_state.params.get_bool("IsOnroadPreview")
    ui_state.params.put_bool("IsOnroadPreview", not is_preview)
    if not is_preview and self._preview_callback is not None:
      self._preview_callback()

  def _update_state(self):
    super()._update_state()
    if self._pending_pairing_grow_animation:
      btn_right = self._pairing_button.rect.x + self._pairing_button.rect.width
      visible_right = self._rect.x + self._rect.width
      if btn_right < visible_right + 50:
        self._pending_pairing_grow_animation = False
        self._pairing_button.trigger_grow_animation()
    is_preview = ui_state.params.get_bool("IsOnroadPreview")
    tint = rl.Color(70, 91, 234, 255) if (self._onroad_preview_btn.enabled and is_preview) else rl.WHITE
    self._onroad_preview_btn.set_bg_tint(tint)
    # always offroad button mirrors the requested state, like Big GUI's
    # Exit/Enable Always Offroad label swap
    if ui_state.always_offroad:
      self._always_offroad_btn.set_value(tr("tap to exit"))
    else:
      self._always_offroad_btn.set_value(tr("tap to enter"))
    # with RecordingMode 0 nothing is recorded, so there is nothing to upload;
    # manager also forces the param off
    self._onroad_uploads_toggle.set_superseded(ui_state.params.get_int("RecordingMode") == 0)
    # safe mode button mirrors the guarded transition's state (parked only)
    from openpilot.sunnypilot.common.safe_mode_runtime import is_safe_mode
    self._safe_mode_btn.set_value(tr("on") if is_safe_mode(ui_state.params) else tr("off"))

  def show_event(self):
    super().show_event()
    self._update_toggles()
    self._update_calib_description()
    if not ui_state.prime_state.is_paired():
      self.set_shown_callback(self._pairing_button.trigger_grow_animation)

  def hide_event(self):
    super().hide_event()
    self.set_shown_callback(None)
    self._pending_pairing_grow_animation = False

  def scroll_to_pairing(self):
    self._scroller._layout()
    offset = (self._pairing_button.rect.x + self._pairing_button.rect.width / 2) - (self._rect.x + self._rect.width / 2)
    self._scroller.scroll_to(offset, smooth=True, block_interrupt=True, block_widget_interaction=True)
    self._pending_pairing_grow_animation = True

  def _on_regulatory(self):
    if not self._fcc_dialog:
      self._fcc_dialog = MiciFccModal(os.path.join(BASEDIR, "openpilot/selfdrive/assets/offroad/mici_fcc.html"))
    gui_app.push_widget(self._fcc_dialog)
