"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections.abc import Callable
import pyray as rl

from opendbc.iqpilot.car.tesla.values import TeslaFlagsIQ
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.iqpilot.widgets.list_view import multiple_button_item, toggle_item

AOL_STEERING_MODE_OPTIONS = [
  (tr("Remain Active"), tr_noop("Remain Active: ALC will remain active when the brake pedal is pressed.")),
  (tr("Pause"), tr_noop("Pause: ALC will pause when the brake pedal is pressed.")),
  (tr("Disengage"), tr_noop("Disengage: ALC will disengage when the brake pedal is pressed.")),
]

AOL_MAIN_CRUISE_BASE_DESC = tr("Note: For vehicles without LFA/LKAS button, disabling this will prevent lateral control engagement.")

STATUS_CHECK_COMPATIBILITY = tr("Start the vehicle to check vehicle compatibility.")
DEFAULT_TO_OFF = tr("This feature defaults to OFF, and does not allow selection due to vehicle limitations.")
STATUS_DISENGAGE_ONLY = tr("This platform only supports Disengage mode due to vehicle limitations.")


class AolSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)
    self._initialize_items()
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._main_cruise_toggle = toggle_item(
      title=lambda: tr("Toggle with Main Cruise"),
      description=AOL_MAIN_CRUISE_BASE_DESC,
      param="AolMainCruiseAllowed",
    )
    self._steering_mode = multiple_button_item(
      param="AolSteeringMode",
      title=lambda: tr("Steering Mode on Brake Pedal"),
      description="",
      buttons=[opt[0] for opt in AOL_STEERING_MODE_OPTIONS],
      inline=False,
      button_width=350,
      callback=self._update_steering_mode_description,
    )

    self.items = [
      self._main_cruise_toggle,
      self._steering_mode,
    ]

  def _update_state(self):
    super()._update_state()
    self._update_toggles()

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    # subtract button
    content_rect = rl.Rectangle(rect.x, rect.y + self._back_button.rect.height + 40, rect.width, rect.height - self._back_button.rect.height - 40)
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()

  @staticmethod
  def _aol_limited_settings() -> bool:
    brand = ""
    if ui_state.is_offroad():
      bundle = ui_state.params.get("CarPlatformBundle")
      if bundle:
        brand = bundle.get("brand", "")
    if not brand:
      brand = ui_state.CP.brand if ui_state.CP else ""

    if brand == "rivian":
      return True
    elif brand == "tesla":
      return not (ui_state.CP_IQ and ui_state.CP_IQ.flags & TeslaFlagsIQ.HAS_VEHICLE_BUS)
    return False

  def _update_steering_mode_description(self, button_index: int):
    base_desc = tr("Choose how Automatic Lane Centering (ALC) behaves after the brake pedal is manually pressed in IQ.Pilot.")
    result = base_desc + "<br><br>"
    for opt in AOL_STEERING_MODE_OPTIONS:
      desc = "<b>" + opt[1] + "</b>" if button_index == AOL_STEERING_MODE_OPTIONS.index(opt) else opt[1]
      result += desc + "<br>"
    self._steering_mode.set_description(result)
    self._steering_mode.show_description(True)

  def _update_toggles(self):
    if ui_state.params.get_bool("AolEnabled"):
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)

    self._update_steering_mode_description(self._steering_mode.action_item.get_selected_button())
    if self._aol_limited_settings():
      ui_state.params.remove("AolMainCruiseAllowed")
      ui_state.params.put_bool("AolUnifiedEngagementMode", True)
      ui_state.params.put("AolSteeringMode", 2)

      self._main_cruise_toggle.action_item.set_enabled(False)
      self._main_cruise_toggle.action_item.set_state(False)
      self._main_cruise_toggle.set_description("<b>" + DEFAULT_TO_OFF + "</b><br>" + AOL_MAIN_CRUISE_BASE_DESC)

      self._steering_mode.action_item.set_enabled(False)
      self._steering_mode.set_description(STATUS_DISENGAGE_ONLY)
      self._steering_mode.action_item.set_selected_button(2)
    else:
      self._main_cruise_toggle.action_item.set_enabled(True)
      self._main_cruise_toggle.set_description(AOL_MAIN_CRUISE_BASE_DESC)

      self._steering_mode.action_item.set_enabled(True)
