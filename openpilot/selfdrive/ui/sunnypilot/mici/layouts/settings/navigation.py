"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json

from openpilot.common.params import Params
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiParamToggle, BigParamControl, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

# 0=off, 1/2 = lane-warning styles (webui panel_catalog "Haptic Feedback (Speed Camera)")
HAPTIC_OPTIONS = [tr("off"), tr("style 1"), tr("style 2")]


class NaviDebugPage(NavScroller):
  """Scrollable dump of the last navigation event handled by CarrotManager."""

  def __init__(self, debug: dict, fallback_message: str = ""):
    super().__init__()

    if not debug:
      self._scroller.add_widget(GreyBigButton(tr("Carrot Navi Debug"), fallback_message or tr("No navigation event received yet.")))
      return

    self._scroller.add_widget(GreyBigButton(tr("Carrot Navi Debug"),
                                            f"Type: {debug.get('type', '')}\n"
                                            f"Event Time: {debug.get('eventTimeMs', 0)} ms\n"
                                            f"Received At: {debug.get('receivedAt', '')}"))

    summary = debug.get('summary')
    if isinstance(summary, dict) and summary:
      for line in json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str).splitlines():
        self._scroller.add_widget(GreyBigButton("", line))

    # The 10 Hz snapshot writer fills these keys instead of `summary`.
    snapshot = {k: v for k, v in debug.items() if k not in ('summary', 'title', 'lines')}
    if snapshot:
      self._scroller.add_widget(GreyBigButton("", "snapshot"))
      for line in json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True, default=str).splitlines():
        self._scroller.add_widget(GreyBigButton("", line))


class NavigationLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()

    self._osm_map_data_toggle = BigParamControl(tr("Enable OSM Map Data"), "OsmMapDataEnabled",
                                                description=tr("Use offline OSM map data for speed limits and road names. Turn off " +
                                                               "to ignore the offline map entirely - useful when navigation is the " +
                                                               "source you trust, since the offline data can be out of date."))

    self._carrot_amap_blind_spot_toggle = BigParamControl(tr("Enable Carrot Blind Spot Data"), "CarrotAmapBlindSpotEnabled",
                                                          description=tr("Parse blind-spot / LiDAR / extBlinker fields from the 7706 UDP stream."))

    # Behaviour switches, not process gates (see Big GUI navigation.py for the details).
    self._carrot_enabled_toggle = BigParamControl(tr("Enable Carrot Navigation"), "CarrotEnabled",
                                                  description=tr("Use Carrot navigation data for map-based features."))
    self._carrot_navi_v2_toggle = BigParamControl(tr("Enable Carrot Navi v2 (7714)"), "CarrotNaviV2Enabled",
                                                  description=tr("Use the 7714 WebSocket v2 rich navigation stream (traffic, lanes, crossroad images). " +
                                                                 "The 7714 link always runs; this only decides whether its data is used."))
    self._carrot_atc_blinker_toggle = BigParamControl(tr("Carrot ATC Turn Signal"), "CarrotAtcBlinkerEnabled",
                                                      description=tr("Let the Carrot app's turn instruction act as a turn signal and steer for exits and turns. " +
                                                                     "On by default; turn off if you don't want navigation to actuate the signal."))
    self._carrot_nav_cruise_speed_toggle = BigParamControl(tr("Navigation Cruise Speed"), "CarrotNavCruiseSpeedEnabled",
                                                           description=tr("Use navigation desired speed to limit cruise speed."))
    self._haptic_speed_camera_toggle = BigMultiParamToggle(tr("Haptic Feedback (Speed Camera)"), "HapticFeedbackWhenSpeedCamera",
                                                           HAPTIC_OPTIONS,
                                                           description=tr("Steering-wheel nudge when carrot decelerates for a speed camera."))

    self._navi_debug_btn = BigButton(tr("Carrot Navi Debug"), tr("VIEW"),
                                     description=tr("View the last navigation event summary handled by CarrotManager."))
    self._navi_debug_btn.set_click_callback(self._on_carrot_navi_debug)

    # order mirrors Big GUI navigation.py _initialize_items
    self._scroller.add_widgets([
      self._osm_map_data_toggle,
      self._carrot_amap_blind_spot_toggle,
      self._carrot_enabled_toggle,
      self._carrot_navi_v2_toggle,
      self._carrot_atc_blinker_toggle,
      self._carrot_nav_cruise_speed_toggle,
      self._haptic_speed_camera_toggle,
      self._navi_debug_btn,
    ])

    # Carrot toggles only make sense offroad, matching Big GUI _update_state.
    self._carrot_enabled_toggle.set_enabled(lambda: ui_state.is_offroad())
    self._carrot_amap_blind_spot_toggle.set_enabled(lambda: ui_state.is_offroad())

  def _update_state(self):
    super()._update_state()

    # Read the param rather than the toggle's cached state so an external change
    # is reflected too (same as Big GUI).
    carrot_on = self._params.get_bool("CarrotEnabled")
    self._carrot_navi_v2_toggle.set_visible(carrot_on)
    self._carrot_nav_cruise_speed_toggle.set_visible(carrot_on)
    self._haptic_speed_camera_toggle.set_visible(carrot_on)
    self._navi_debug_btn.set_visible(carrot_on)

  def show_event(self):
    super().show_event()
    # Mirror external param changes into the toggles.
    for toggle in (self._osm_map_data_toggle, self._carrot_enabled_toggle, self._carrot_navi_v2_toggle,
                   self._carrot_atc_blinker_toggle, self._carrot_nav_cruise_speed_toggle,
                   self._carrot_amap_blind_spot_toggle):
      toggle.refresh()
    self._haptic_speed_camera_toggle.refresh()

  def _on_carrot_navi_debug(self):
    # CarrotNaviDebug is registered as a JSON param (params_keys.h), so Params.get()
    # already decodes it to a dict; tolerate raw str/bytes like Big GUI does.
    raw = self._params.get("CarrotNaviDebug")
    if isinstance(raw, (bytes, bytearray)):
      raw = raw.decode("utf-8", errors="replace")

    if isinstance(raw, dict):
      debug = raw
    elif isinstance(raw, str) and raw.strip():
      try:
        parsed = json.loads(raw)
      except Exception:
        gui_app.push_widget(NaviDebugPage({}, fallback_message=raw))
        return
      debug = parsed if isinstance(parsed, dict) else {}
    else:
      debug = {}

    gui_app.push_widget(NaviDebugPage(debug))
