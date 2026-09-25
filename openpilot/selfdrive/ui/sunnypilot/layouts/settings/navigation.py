"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import threading

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.html_render import HtmlModalSP
from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import CarrotTuningLayout
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, option_item_sp, button_item_sp, simple_button_item_sp
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller
from enum import IntEnum


class PanelType(IntEnum):
  NAVIGATION = 0
  CARROT_TUNING = 1


class NavigationLayout(Widget):
  def __init__(self):
    super().__init__()

    self._params = Params()
    self._current_panel = PanelType.NAVIGATION
    self._amap_key_test_thread: threading.Thread | None = None
    self._amap_key_test_result: tuple[bool, str] | None = None
    self._carrot_tuning_layout = CarrotTuningLayout(lambda: self._set_current_panel(PanelType.NAVIGATION))
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._amap_map_data_enabled = toggle_item_sp(
      title=tr("Enable Amap Map Data"),
      description=tr("Use Amap (Gaode) online map data for speed limits and road names in China."),
      param="AmapMapDataEnabled",
    )

    self._carrot_amap_blind_spot_enabled = toggle_item_sp(
      title=tr("Enable Amap Blind Spot Data"),
      description=tr("Parse blind-spot / LiDAR / extBlinker fields from the 7706 UDP stream."),
      param="CarrotAmapBlindSpotEnabled",
    )

    self._carrot_enabled = toggle_item_sp(
      title=tr("Enable Carrot Navigation"),
      description=tr("Use Carrot navigation data for map-based features."),
      param="CarrotEnabled",
    )

    self._amap_api_key = button_item_sp(
      title=tr("Amap API Key"),
      button_text=tr("EDIT"),
      description=tr("API key for Amap services. Tap EDIT to enter or update the key."),
      callback=self._on_amap_api_key,
    )

    self._amap_api_key_test = button_item_sp(
      title=tr("Test Amap API Key"),
      button_text=lambda: tr("TESTING...") if self._amap_key_test_running() else tr("TEST"),
      description=tr("Ask the Amap road name and speed limit services with the stored key and report which ones work."),
      callback=self._on_amap_api_key_test,
    )

    self._carrot_tuning_button = simple_button_item_sp(
      button_text=lambda: tr("Carrot Tuning"),
      button_width=800,
      callback=lambda: self._set_current_panel(PanelType.CARROT_TUNING),
    )

    items = [
      self._amap_map_data_enabled,
      self._carrot_amap_blind_spot_enabled,
      self._carrot_enabled,
      self._amap_api_key,
      self._amap_api_key_test,
      self._carrot_tuning_button,
    ]
    return items

  def _update_state(self):
    super()._update_state()

    offroad = ui_state.is_offroad()
    self._amap_map_data_enabled.action_item.set_enabled(offroad)
    self._carrot_amap_blind_spot_enabled.action_item.set_enabled(offroad)
    self._carrot_enabled.action_item.set_enabled(offroad)
    self._amap_api_key.action_item.set_enabled(offroad)
    self._amap_api_key_test.action_item.set_enabled(offroad)

    current_key = self._params.get("AmapApiKey") or ""
    masked = "" if not current_key else "*" * min(len(current_key), 12)
    self._amap_api_key.action_item.set_value(masked)

    # The worker thread cannot touch the render stack, so the result is handed
    # over here and the dialog is pushed from the UI thread.
    if self._amap_key_test_result is not None:
      ok, message = self._amap_key_test_result
      self._amap_key_test_result = None
      self._show_amap_key_test_result(ok, message)

  def _on_amap_api_key(self):
    current_key = self._params.get("AmapApiKey") or ""
    dialog = InputDialogSP(
      title=tr("Enter Amap API Key"),
      sub_title=tr("Your key is stored locally and is not uploaded."),
      current_text=current_key,
      param="AmapApiKey",
    )
    dialog.show()

  def _amap_key_test_running(self) -> bool:
    return self._amap_key_test_thread is not None and self._amap_key_test_thread.is_alive()

  def _on_amap_api_key_test(self):
    if self._amap_key_test_running():
      return
    self._amap_key_test_result = None
    self._amap_key_test_thread = threading.Thread(target=self._run_amap_key_test, daemon=True)
    self._amap_key_test_thread.start()

  def _run_amap_key_test(self):
    """Runs off the UI thread: HTTP probes take seconds and must not block rendering."""
    key = self._params.get("AmapApiKey") or ""
    try:
      from openpilot.sunnypilot.mapd.live_map_data.amap_map_data import check_api_key
      ok, message = check_api_key(key)
    except Exception as e:
      ok, message = False, tr("Test could not run: {}").format(e)
    self._amap_key_test_result = (ok, message)

  def _show_amap_key_test_result(self, ok: bool, message: str):
    heading = tr("Amap API key is valid") if ok else tr("Amap API key has a problem")
    body = message.replace("\n", "<br>")
    gui_app.push_widget(HtmlModalSP(text=f"<b>{heading}</b><br><br>{body}"))

  def _render(self, rect):
    if self._current_panel == PanelType.CARROT_TUNING:
      self._carrot_tuning_layout.render(rect)
    else:
      self._scroller.render(rect)

  def _set_current_panel(self, panel: PanelType):
    self._current_panel = panel
    if panel == PanelType.CARROT_TUNING:
      self._carrot_tuning_layout.show_event()

  def show_event(self):
    self._set_current_panel(PanelType.NAVIGATION)
    self._scroller.show_event()
