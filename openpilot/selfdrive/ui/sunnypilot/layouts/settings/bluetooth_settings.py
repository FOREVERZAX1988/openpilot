"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, TextAlignment
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.scroll_panel import GuiScrollPanel
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.toggle import Toggle

# Supported actions for button mapping
ACTIONS = (
  'none', 'accelCruise', 'decelCruise', 'gapAdjustCruise', 'lfaButton', 'cancel',
  'accelCruiseLong', 'decelCruiseLong', 'gapAdjustCruiseLong', 'lfaButtonLong', 'cancelLong',
  'laneLeft', 'laneRight', 'paddleDecel', 'carrotCruise',
)

# Action Buttons in a device row are built with this font size / Label padding.
# Widths must be measured with the *same* values, or the Label is wider than its
# button and wrap_text() breaks the caption over two lines ("Disconnec" + "t").
DEVICE_ACTION_FONT_SIZE = 40
DEVICE_ACTION_TEXT_PADDING = 20  # Button -> Label default text_padding, per side

# Mapping-editor vertical metrics. The body is scrollable, but these keep the
# whole editor on one screen at 1080p so the Save row is reachable without it.
EDITOR_PROFILE_ROW_H = 78
EDITOR_TOGGLE_ROW_H = 70
EDITOR_HEADING_H = 56
EDITOR_GESTURE_HEADER_H = 46
EDITOR_ROW_H = 60
EDITOR_ROW_GAP = 8
EDITOR_FOOTER_GAP = 8
EDITOR_FOOTER_H = 72

MAPPING_BUTTONS = ('up', 'down', 'left', 'right', 'center', '1', '2')
GESTURES = ('single', 'double', 'long')
GESTURE_LABELS = {'single': 'Short', 'double': 'Double', 'long': 'Long'}

# Default single-press mapping expanded to all gesture tokens for the Yiser-J6 preset.
BT_DEFAULTS = {
  'up_single': 'accelCruise', 'up_double': 'none', 'up_long': 'none',
  'down_single': 'decelCruise', 'down_double': 'none', 'down_long': 'none',
  'left_single': 'laneLeft', 'left_double': 'none', 'left_long': 'none',
  'right_single': 'laneRight', 'right_double': 'none', 'right_long': 'none',
  'center_single': 'paddleDecel', 'center_double': 'none', 'center_long': 'none',
  '1_single': 'gapAdjustCruise', '1_double': 'none', '1_long': 'none',
  '2_single': 'none', '2_double': 'none', '2_long': 'none',
}

_CONFIG_PATH = '/data/params/d/CarrotBluetooth'
_RUNTIME_PATH = '/dev/shm/carrot-bluetooth'

# The carrot API server on 7000 owns Bluetooth for every client - this panel, the
# companion app and any script - so a mapping edited on the phone is the mapping the
# daemon runs. (This panel previously called a port nothing listened on.)
API_BASE = 'http://127.0.0.1:7000'


def _api_path(operation: str | None = None) -> str:
  base = f'{API_BASE}/api/bluetooth'
  return f'{base}/{operation}' if operation else base


def _http_get(path: str) -> dict:
  import urllib.request
  try:
    with urllib.request.urlopen(path, timeout=5) as resp:
      import json
      return json.loads(resp.read())
  except Exception:
    return {}


def _http_post(operation: str, data: dict | None = None) -> dict:
  import json
  import urllib.request
  try:
    body = b'{}' if data is None else json.dumps(data).encode()
    req = urllib.request.Request(_api_path(operation), data=body,
                                headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
      return json.loads(resp.read())
  except Exception as e:
    return {'error': str(e)}


@dataclass
class BTDevice:
  address: str = ''
  name: str = ''
  paired: bool = False
  connected: bool = False
  rssi: int | None = None
  battery: int | None = None
  enabled: bool = False
  grabbed: bool = False
  profile: str = 'generic'
  mapping: dict = field(default_factory=dict)


class BTPanel(IntEnum):
  DEVICES = 0
  EDITOR = 1
  ADVANCED = 2


@dataclass
class BTRuntime:
  alive: bool = False
  stationary: bool = False
  grabbed: list = field(default_factory=list)
  learning: dict | None = None
  errors: dict = field(default_factory=dict)
  recent_events: list = field(default_factory=list)


@dataclass
class BTState:
  has_bluez: bool = False
  service_running: bool = False
  available: bool = False
  has_uart: bool = False
  has_btpower: bool = False
  radio_enabled: bool = False
  discoverable: bool = False
  local_name: str = ''
  discovering: bool = False
  runtime: BTRuntime = field(default_factory=BTRuntime)
  devices: list[BTDevice] = field(default_factory=list)
  config_devices: dict = field(default_factory=dict)
  error: str = ''
  prompt: dict | None = None
  learning_addr: str | None = None


class CarrotBluetoothLayout(Widget):
  """
  Native GUI panel for Carrot Bluetooth HID remote configuration.
  """

  def __init__(self):
    super().__init__()

    # Must be initialized here (not only in show_event) because _fetch_state()
    # checks self._running at the top of its body, before any rendering happens.
    # If render() is called before show_event() (e.g. a timing edge case in the
    # settings panel manager), an AttributeError: "_running" would crash the UI.
    self._running = False
    self._state = BTState()
    self._state_lock = threading.Lock()
    self._selected_address: str | None = None
    self._draft: BTDevice | None = None
    self._dirty = False
    self._panel = BTPanel.DEVICES
    self._last_fetch = 0.0
    self._fetch_interval = 1.0
    self._auto_scanned = False
    self._installing = False

    # Scanning is only "active" for the UI while we expect it to be. This
    # prevents the status line from getting stuck on "Scanning..." when BlueZ
    # leaves the adapter discovering flag set after a timeout/edge case.
    self._scanning_until = 0.0

    # Pairing prompt handling: remember dismissed prompt ids so we don't
    # repeatedly push dialog widgets for the same prompt.
    self._dismissed_prompt_ids: set[str] = set()
    self._keyboard = Keyboard(max_text_size=16, min_text_size=1)

    # UI dimensions
    self._item_height = 160
    self._btn_height = 80
    self._label_height = 60
    self._mapping_row_height = EDITOR_ROW_H
    self._gesture_col_width = 220
    self._padding = 30
    self._content_width = 0

    # Scroll panels: one for the device list, one for the mapping editor body
    # (separate instances so their offsets don't bleed into each other).
    self._scroll_panel = GuiScrollPanel()
    self._editor_scroll = GuiScrollPanel()

    # Per-device row button cache (re-created when device set changes)
    self._device_btns: dict[str, Button] = {}
    # (address, action) -> Button. One instance per row: see _row_action_btn.
    self._row_action_btns: dict[tuple[str, str], Button] = {}

    # Status / error labels
    self._status_text = ''
    self._error_text = ''

    # Buttons / toggles
    self._scan_btn = Button(tr("Scan"), self._on_scan_clicked, button_style=ButtonStyle.NORMAL, font_size=60, border_radius=30)
    self._adv_btn = Button(tr("Advanced"), self._on_advanced_clicked, button_style=ButtonStyle.NORMAL, font_size=46, border_radius=30)
    self._install_btn = Button(tr("Install Bluetooth"), self._on_install_clicked, button_style=ButtonStyle.PRIMARY, font_size=52, border_radius=24)
    self._enable_btn = Button(tr("Enable Bluetooth"), self._on_enable_service_clicked, button_style=ButtonStyle.PRIMARY, font_size=52, border_radius=24)
    self._retry_btn = Button(tr("Retry"), self._on_retry_clicked, button_style=ButtonStyle.PRIMARY, font_size=52, border_radius=24)
    self._radio_toggle = Toggle(self._state.radio_enabled, self._on_radio_toggled)
    self._discoverable_toggle = Toggle(False, self._on_discoverable_toggled)
    # font_size 40: "Test / Learn" must fit its quarter-width footer cell without
    # wrap_text() splitting it onto a second line.
    self._save_btn = Button(tr("Save"), self._on_save_clicked, button_style=ButtonStyle.PRIMARY, font_size=40, border_radius=15)
    self._name_action_btn = Button(tr("Edit"), self._on_name_action_clicked, button_style=ButtonStyle.NORMAL, font_size=40, border_radius=15)
    self._reset_btn = Button(tr("Reset Bluetooth"), self._on_reset_clicked, button_style=ButtonStyle.DANGER, font_size=45, border_radius=15)
    self._test_btn = Button(tr("Test / Learn"), self._on_test_clicked, button_style=ButtonStyle.NORMAL, font_size=40, border_radius=15)
    self._stop_btn = Button(tr("Stop Test"), self._on_stop_clicked, button_style=ButtonStyle.DANGER, font_size=40, border_radius=15)
    self._back_btn = Button(tr("Back"), self._on_back_clicked, button_style=ButtonStyle.NORMAL, font_size=45, border_radius=15)
    self._edit_btn = Button(tr("Edit"), self._on_edit_clicked, button_style=ButtonStyle.NORMAL, font_size=40, border_radius=15)

    self._last_radio_state = self._state.radio_enabled
    self._last_discoverable_state = self._state.discoverable

    # Gesture buttons for mapping
    self._gesture_btns: dict[str, dict[str, Button]] = {}
    for btn_name in MAPPING_BUTTONS:
      self._gesture_btns[btn_name] = {}
      for gesture in GESTURES:
        token = f'{btn_name}_{gesture}'
        b = Button('', lambda _t=token: self._on_mapping_clicked(_t),
                   button_style=ButtonStyle.TRANSPARENT_WHITE_BORDER, font_size=35, border_radius=10)
        self._gesture_btns[btn_name][gesture] = b

    # Device name input
    self._name_input = ''
    self._name_focused = False

    # Events display
    self._last_event_text = ''
    self._seen_event_ids: set = set()

  def show_event(self) -> None:
    self._running = True
    self._selected_address = None
    self._draft = None
    self._dirty = False
    self._panel = BTPanel.DEVICES
    self._auto_scanned = False
    self._installing = False
    self._scanning_until = 0.0
    self._dismissed_prompt_ids.clear()
    self._fetch_state()

  def hide_event(self) -> None:
    self._running = False

  def _is_scanning_active(self, state: BTState) -> bool:
    """True only while we believe a scan is still in progress."""
    return state.discovering and time.monotonic() < self._scanning_until

  def _fetch_state(self) -> None:
    if not self._running:
      return
    try:
      data = _http_get(_api_path())
      state = self._parse_state(data)
      with self._state_lock:
        self._state = state
        self._error_text = state.error
        self._status_text = self._status_for_state(state)
    except Exception as e:
      with self._state_lock:
        self._error_text = str(e)
    self._last_fetch = time.monotonic()

  def _status_for_state(self, state: BTState) -> str:
    if not state.has_bluez:
      return tr("Bluetooth is not installed")
    if not state.service_running:
      return tr("Bluetooth service is stopped")
    if not state.has_uart and not state.has_btpower:
      return tr("Bluetooth radio hardware not detected")
    if not state.has_uart:
      return tr("Bluetooth UART not exposed by this AGNOS kernel")
    if not state.has_btpower:
      return tr("Bluetooth power node not detected")
    if not state.available:
      return tr("No Bluetooth adapter found")
    if self._is_scanning_active(state):
      return tr("Scanning...")
    if not state.radio_enabled:
      return tr("Bluetooth disabled")
    return tr("Ready")

  def _parse_state(self, data: dict) -> BTState:
    state = BTState()
    state.has_bluez = data.get('hasBluez', False)
    state.service_running = data.get('serviceRunning', False)
    state.available = data.get('available', False)
    state.has_uart = data.get('hasUart', False)
    state.has_btpower = data.get('hasBtpower', False)
    state.radio_enabled = data.get('radioEnabled', False)
    state.discoverable = data.get('discoverable', False)
    state.local_name = data.get('localName', '') or ''
    state.error = data.get('error', '') or ''

    rt = data.get('runtime', {})
    state.runtime = BTRuntime(
      alive=rt.get('alive', False),
      stationary=rt.get('stationary', False),
      grabbed=rt.get('grabbed', []),
      errors=rt.get('errors', {}),
    )
    lr = rt.get('learning')
    state.learning_addr = lr.get('address') if lr else None

    state.devices = []
    for d in data.get('devices', []):
      addr = d.get('address', '')
      cfg = data.get('config', {}).get('devices', {}).get(addr, {})
      dev = BTDevice(
        address=addr,
        name=d.get('name', addr),
        paired=d.get('paired', False),
        connected=d.get('connected', False),
        rssi=d.get('rssi'),
        battery=d.get('battery'),
        enabled=cfg.get('enabled', False),
        grabbed=addr in state.runtime.grabbed,
        profile=cfg.get('profile', 'generic'),
        mapping=cfg.get('mapping', {}),
      )
      state.devices.append(dev)
    state.config_devices = data.get('config', {}).get('devices', {})

    state.prompt = data.get('prompt')

    adapters = data.get('adapters', [])
    state.discovering = any(a.get('discovering', False) for a in adapters)

    return state

  def _render(self, rect: rl.Rectangle) -> None:
    self._content_width = rect.width

    now = time.monotonic()
    if now - self._last_fetch > self._fetch_interval:
      self._fetch_state()

    with self._state_lock:
      state = self._state
      error_text = self._error_text
      status_text = self._status_text

    if self._panel == BTPanel.EDITOR and self._draft is not None:
      self._render_editor(rect, state)
    elif self._panel == BTPanel.ADVANCED:
      self._render_advanced(rect, state)
    else:
      self._render_main(rect, state, error_text, status_text)
      if self._panel == BTPanel.DEVICES:
        self._handle_prompt(state)

    self._maybe_auto_scan(state)

  def _maybe_auto_scan(self, state: BTState) -> None:
    if self._auto_scanned:
      return
    if not state.available or not state.radio_enabled:
      return
    self._auto_scanned = True
    self._scanning_until = time.monotonic() + 32
    self._http_async('scan')

  def _render_main(self, rect: rl.Rectangle, state: BTState, error_text: str, status_text: str) -> None:
    y = rect.y

    # Not installed
    if not state.has_bluez:
      self._render_empty_state(rect, icon='📡', title=tr("Bluetooth is not installed"),
                               desc=tr("Install BlueZ to enable Bluetooth HID remotes and device management."),
                               btn=self._install_btn, btn_label=tr("Installing...") if self._installing else None)
      return

    # Service not running
    if not state.service_running:
      self._render_empty_state(rect, icon='🔘', title=tr("Bluetooth service is stopped"),
                               desc=tr("Start the Bluetooth service to scan and pair devices."),
                               btn=self._enable_btn)
      return

    # Required hardware nodes missing (e.g. this device/AGNOS variant has no ttyHS1)
    if not state.has_uart or not state.has_btpower:
      if not state.has_uart and not state.has_btpower:
        title = tr("Bluetooth radio hardware not detected")
        desc = tr("This device or AGNOS build lacks the required Bluetooth UART and power nodes.")
      elif not state.has_uart:
        title = tr("Bluetooth UART not available")
        desc = tr("This AGNOS kernel does not expose /dev/ttyHS1. Reflash to a Bluetooth-capable AGNOS build.")
      else:
        title = tr("Bluetooth power node not detected")
        desc = tr("This device or AGNOS build lacks /dev/btpower.")
      self._render_empty_state(rect, icon='📵', title=title, desc=desc, btn=self._retry_btn)
      return

    # No adapter
    if not state.available:
      self._render_empty_state(rect, icon='📵', title=tr("No Bluetooth adapter found"),
                               desc=tr("Flash an AGNOS with Bluetooth support or plug in a USB Bluetooth dongle."),
                               btn=self._retry_btn)
      return

    # Normal device list UI
    content_top = self._render_header(rect, state, error_text)

    # The Scan / Advanced buttons render (and consume input) before the list. If one
    # of them was tapped we already changed panel, so stop here - otherwise the list
    # below is still processed in the same frame against the panel we just left.
    if self._panel != BTPanel.DEVICES:
      return

    self._render_devices(rect, content_top, state)

  def _render_empty_state(self, rect: rl.Rectangle, icon: str, title: str, desc: str,
                          btn: Button, btn_label: str | None = None) -> None:
    y = rect.y + 120
    gui_label(rl.Rectangle(rect.x, y, rect.width, 120), icon, font_size=110, alignment=TextAlignment.CENTER)
    y += 140
    gui_label(rl.Rectangle(rect.x, y, rect.width, 80), title, font_size=52, alignment=TextAlignment.CENTER)
    y += 90
    gui_label(rl.Rectangle(rect.x + self._padding, y, rect.width - self._padding * 2, 120), desc,
              font_size=38, alignment=TextAlignment.CENTER, color=rl.Color(170, 170, 170, 255))
    y += 160
    if btn_label:
      btn.set_text(btn_label)
      btn.set_enabled(False)
    else:
      btn.set_enabled(True)
    btn_w = min(520, rect.width - self._padding * 2)
    btn.set_rect(rl.Rectangle(rect.x + (rect.width - btn_w) / 2, y, btn_w, 110))
    btn.render()

  def _render_header(self, rect: rl.Rectangle, state: BTState, error_text: str) -> float:
    y = rect.y + 20
    top_h = 100
    can_act = state.available
    discovering = self._is_scanning_active(state)

    # Scan / Stop button
    self._scan_btn.set_text(tr("Stop") if discovering else tr("Scan"))
    self._scan_btn.set_enabled(can_act and (discovering or state.radio_enabled))
    self._scan_btn.set_rect(rl.Rectangle(rect.x, y, 400, top_h))
    self._scan_btn.render()

    # Advanced button
    self._adv_btn.set_enabled(can_act)
    self._adv_btn.set_rect(rl.Rectangle(rect.x + rect.width - 320, y, 320, top_h))
    self._adv_btn.render()

    y += top_h + 40

    # Error
    if error_text:
      gui_label(rl.Rectangle(rect.x, y, rect.width, self._label_height), error_text[:80], font_size=38,
                alignment=TextAlignment.CENTER, color=rl.Color(255, 80, 80, 255))
      y += self._label_height

    return y + 20

  def _render_devices(self, rect: rl.Rectangle, content_top: float, state: BTState) -> None:
    start_y = content_top

    paired = [d for d in state.devices if d.paired]
    found = sorted([d for d in state.devices if not d.paired], key=lambda d: d.rssi or -1000, reverse=True)

    if not paired and not found:
      gui_label(rl.Rectangle(rect.x, start_y + 80, rect.width, 80), tr("No devices found"),
                font_size=45, alignment=TextAlignment.CENTER, color=rl.Color(150, 150, 150, 255))
      return

    row_h = 140
    group_title_h = 60
    total_h = 0
    if paired:
      total_h += group_title_h + len(paired) * row_h
    if found:
      total_h += group_title_h + len(found) * row_h

    # The list lives *below* the header. Laying it out from rect.y made the first
    # row sit underneath the Scan / Advanced buttons: only a sliver of its text
    # showed at the top, yet its full-width row button stayed tappable, so tapping
    # "Advanced" also opened that device's mapping editor.
    content_rect = rl.Rectangle(rect.x, start_y, rect.width, total_h)
    scissor_rect = rl.Rectangle(rect.x, start_y, rect.width, max(0.0, rect.height - (start_y - rect.y)))
    offset = self._scroll_panel.update(scissor_rect, content_rect)

    rl.begin_scissor_mode(int(scissor_rect.x), int(scissor_rect.y), int(scissor_rect.width), int(scissor_rect.height))
    y = start_y + offset
    if paired:
      gui_label(rl.Rectangle(rect.x + self._padding, y, rect.width, group_title_h), tr("Paired devices"),
                font_size=36, alignment=TextAlignment.LEFT, color=rl.Color(150, 150, 150, 255))
      y += group_title_h
      for i, dev in enumerate(paired):
        item_rect = rl.Rectangle(rect.x, y, rect.width, row_h)
        if rl.check_collision_recs(item_rect, scissor_rect):
          self._render_device_row(item_rect, dev, state, is_last=i == len(paired) - 1 and not found,
                                  clip_rect=scissor_rect)
        y += row_h

    if found:
      gui_label(rl.Rectangle(rect.x + self._padding, y, rect.width, group_title_h), tr("Available devices"),
                font_size=36, alignment=TextAlignment.LEFT, color=rl.Color(150, 150, 150, 255))
      y += group_title_h
      for i, dev in enumerate(found):
        item_rect = rl.Rectangle(rect.x, y, rect.width, row_h)
        if rl.check_collision_recs(item_rect, scissor_rect):
          self._render_device_row(item_rect, dev, state, is_last=i == len(found) - 1,
                                  clip_rect=scissor_rect)
        y += row_h

    rl.end_scissor_mode()

  def _fitted_btn_width(self, label: str, font_size: int, min_width: int) -> int:
    """Width that fits *label* on one line in a Button rendered at *font_size*.

    Measure with the same font size and padding the Button/Label really use.
    Measuring at a different size let the caption outgrow the button, and
    wrap_text() then split it over two lines ("Disconnec" + "t").
    """
    text_w = measure_text_cached(gui_app.font(FontWeight.MEDIUM), label, font_size).x
    return max(min_width, int(text_w + DEVICE_ACTION_TEXT_PADDING * 2 + 20))

  def _action_btn_width(self, label: str) -> int:
    """Width for a device-row action Button (font size 40, row-sized)."""
    return self._fitted_btn_width(label, DEVICE_ACTION_FONT_SIZE, 160)

  def _row_action_btn(self, address: str, action: str) -> Button:
    """One Button instance per (row, action) pair.

    A single shared instance is rendered once per device row *within the same
    frame*. Widget._process_mouse_events keys off per-instance press state, so
    the second render reset the state the first had just set -- a normal tap
    (press in one frame, release in the next) on "Pair" was silently dropped.
    """
    key = (address, action)
    btn = self._row_action_btns.get(key)
    if btn is None:
      btn = Button('', None, button_style=ButtonStyle.NORMAL,
                   font_size=DEVICE_ACTION_FONT_SIZE, border_radius=15)
      btn.set_touch_valid_callback(lambda: self._scroll_panel.is_touch_valid())
      self._row_action_btns[key] = btn
    return btn

  def _render_device_row(self, rect: rl.Rectangle, dev: BTDevice, state: BTState, is_last: bool,
                         clip_rect: rl.Rectangle | None = None) -> None:
    """Network-style row: text left, signal/actions right, separator.

    The row's tap target is the *text column* only, and its hit area is clipped
    to the visible band. A full-width row button used to swallow taps meant for
    the Pair / Connect / Forget action buttons, and an unclipped one stayed
    tappable underneath the header while the row itself scrolled out of view.
    """
    btn_gap = 16

    # Compute action buttons from right edge.
    if not dev.paired:
      action_btns = [
        (self._row_action_btn(dev.address, 'pair'), self._action_btn_width(tr("Pair")), tr("Pair"),
         ButtonStyle.PRIMARY, lambda: self._confirm_pair(dev)),
      ]
    else:
      conn_label = tr("Disconnect") if dev.connected else tr("Connect")
      action_btns = [
        (self._row_action_btn(dev.address, 'connect'), self._action_btn_width(conn_label), conn_label,
         ButtonStyle.NORMAL if dev.connected else ButtonStyle.PRIMARY,
         lambda: self._on_device_action(dev, 'connect' if not dev.connected else 'disconnect')),
        (self._row_action_btn(dev.address, 'forget'), self._action_btn_width(tr("Forget")), tr("Forget"),
         ButtonStyle.DANGER, lambda: self._confirm_forget(dev)),
      ]

    total_action_w = sum(w for _, w, _, _, _ in action_btns) + btn_gap * (len(action_btns) - 1)
    action_right = rect.x + rect.width - self._padding

    # RSSI column to the left of action buttons.
    rssi_str = ''
    rssi_w = 0
    if dev.rssi is not None:
      rssi_str = f"{dev.rssi} dBm"
      rssi_size = measure_text_cached(gui_app.font(), rssi_str, 32)
      rssi_w = rssi_size.x
    rssi_col_w = max(110, rssi_w + 20)
    rssi_right = action_right - total_action_w - self._padding

    # Main text area (left of RSSI/actions) is scissored.
    main_right = rssi_right - rssi_col_w - self._padding
    text_x = rect.x + self._padding

    # Row button == text column (left of RSSI/actions), hit area clipped to the
    # visible band so the hidden part of a scrolled row is not tappable.
    text_rect = rl.Rectangle(rect.x, rect.y, max(0.0, main_right - rect.x), rect.height)
    row_btn = self._device_btns.get(dev.address)
    if row_btn is None:
      # Empty caption on purpose: the row's text is drawn below, scissored to the
      # text column. Putting the device name on the Button drew a second,
      # un-clipped copy (two overlapping names, and long names ran under the
      # RSSI / action buttons).
      row_btn = Button('', lambda _d=dev: self._on_row_clicked(_d),
                       font_size=50, text_alignment=TextAlignment.LEFT,
                       button_style=ButtonStyle.TRANSPARENT_WHITE_TEXT)
      row_btn.set_touch_valid_callback(lambda: self._scroll_panel.is_touch_valid())
      self._device_btns[dev.address] = row_btn
    row_btn.set_parent_rect(rl.get_collision_rec(text_rect, clip_rect) if clip_rect is not None else text_rect)
    row_btn.render(text_rect)

    rl.begin_scissor_mode(int(text_rect.x), int(text_rect.y), int(text_rect.width), int(text_rect.height))

    name_y = rect.y + 22
    rl.draw_text_ex(gui_app.font(), dev.name or dev.address, rl.Vector2(text_x, name_y), 50, 0, rl.WHITE)

    status_parts = [dev.address]
    if dev.connected:
      status_parts.append(tr("Connected"))
    elif dev.paired:
      status_parts.append(tr("Paired"))
    if dev.battery is not None:
      status_parts.append(f"{tr('Battery')} {dev.battery}%")
    status_str = ' · '.join(status_parts)
    rl.draw_text_ex(gui_app.font(), status_str, rl.Vector2(text_x, rect.y + 76), 34, 0, rl.Color(160, 160, 160, 255))

    if dev.address in state.config_devices:
      cfg = state.config_devices[dev.address]
      mapping_status = tr("Mapping on") if cfg.get('enabled') else tr("Mapping off")
      if dev.grabbed:
        mapping_status += ' · ' + tr("Receiving input")
      rl.draw_text_ex(gui_app.font(), mapping_status, rl.Vector2(text_x, rect.y + 112), 32, 0, rl.Color(120, 200, 120, 255))

    rl.end_scissor_mode()

    # Draw RSSI
    if dev.rssi is not None:
      rssi_y = rect.y + (rect.height - 32) / 2
      rl.draw_text_ex(gui_app.font(), rssi_str, rl.Vector2(rssi_right - rssi_w, rssi_y),
                      32, 0, rl.Color(120, 180, 255, 255))

    # Draw action buttons
    x = action_right - total_action_w
    for btn, w, label, style, cb in action_btns:
      btn.set_text(label)
      btn.set_button_style(style)
      btn.set_enabled(True)
      btn.set_touch_valid_callback(lambda: self._scroll_panel.is_touch_valid())
      btn_rect = rl.Rectangle(x, rect.y + (rect.height - self._btn_height) // 2, w, self._btn_height)
      btn.set_click_callback(cb)
      btn.set_parent_rect(rl.get_collision_rec(btn_rect, clip_rect) if clip_rect is not None else btn_rect)
      btn.set_rect(btn_rect)
      btn.render()
      x += w + btn_gap

    # Separator line like the network list.
    if not is_last:
      line_y = int(rect.y + rect.height - 1)
      rl.draw_line(int(rect.x + self._padding), line_y, int(rect.x + rect.width - self._padding), line_y, rl.Color(80, 80, 80, 255))

  def _confirm_pair(self, dev: BTDevice) -> None:
    def on_result(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._scanning_until = time.monotonic() + 32
        self._http_async('pair', {'address': dev.address})
    dialog = ConfirmDialog("", tr("Pair"), tr("Cancel"), callback=on_result)
    dialog.set_text(tr('Pair with "{}"?').format(dev.name or dev.address))
    gui_app.push_widget(dialog)

  def _confirm_forget(self, dev: BTDevice) -> None:
    def on_result(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._on_device_action(dev, 'forget')
    dialog = ConfirmDialog("", tr("Forget"), tr("Cancel"), callback=on_result)
    dialog.set_text(tr('Forget "{}"?').format(dev.name or dev.address))
    gui_app.push_widget(dialog)

  def _handle_prompt(self, state: BTState) -> None:
    prompt = state.prompt
    if not prompt:
      self._dismissed_prompt_ids.clear()
      return
    pid = prompt.get('id')
    if not pid or pid in self._dismissed_prompt_ids:
      return
    self._dismissed_prompt_ids.add(pid)

    kind = prompt.get('kind', '')
    value = prompt.get('value', '')

    if kind in ('DisplayPinCode', 'DisplayPasskey'):
      dialog = ConfirmDialog("", tr("OK"), cancel_text="", callback=None)
      dialog.set_text(tr("Pairing code: {}").format(value))
      gui_app.push_widget(dialog)
      return

    if kind in ('RequestConfirmation', 'RequestAuthorization', 'AuthorizeService'):
      def on_confirm(result: DialogResult):
        self._http_async('answer', {'id': pid, 'value': result == DialogResult.CONFIRM})
      dialog = ConfirmDialog("", tr("Confirm"), tr("Cancel"), callback=on_confirm)
      dialog.set_text(tr("Confirm pairing with \"{}\"?").format(value))
      gui_app.push_widget(dialog)
      return

    if kind == 'RequestPinCode':
      def on_pin(result: DialogResult):
        self._http_async('answer', {'id': pid, 'value': False if result != DialogResult.CONFIRM else self._keyboard.text})
      self._keyboard.reset(min_text_size=1)
      self._keyboard.set_title(tr("Enter PIN"), tr("for \"{}\"").format(value) if value else "")
      self._keyboard.set_text("")
      self._keyboard.set_callback(on_pin)
      gui_app.push_widget(self._keyboard)
      return

    if kind == 'RequestPasskey':
      def on_passkey(result: DialogResult):
        self._http_async('answer', {'id': pid, 'value': False if result != DialogResult.CONFIRM else self._keyboard.text})
      self._keyboard.reset(min_text_size=1)
      self._keyboard.set_title(tr("Enter passkey"), tr("for \"{}\"").format(value) if value else "")
      self._keyboard.set_text("")
      self._keyboard.set_callback(on_passkey)
      gui_app.push_widget(self._keyboard)

  def _editor_gesture_col_width(self, rect: rl.Rectangle) -> float:
    """Column width for the gesture buttons: use the spare width so action
    captions ("Cruise \u2212 Long") fit instead of wrapping or eliding."""
    first_col_x = rect.x + self._padding + 150
    usable = (rect.x + rect.width - self._padding) - first_col_x
    return max(self._gesture_col_width, usable / len(GESTURES))

  def _editor_body_height(self) -> float:
    """Height of the scrollable editor body. Must match the layout in
    _render_editor so the scrollbar range is right."""
    rows = EDITOR_ROW_H + EDITOR_ROW_GAP
    return (EDITOR_PROFILE_ROW_H + EDITOR_TOGGLE_ROW_H + EDITOR_HEADING_H + EDITOR_GESTURE_HEADER_H +
            len(MAPPING_BUTTONS) * rows + EDITOR_FOOTER_GAP + EDITOR_FOOTER_H)

  def _render_editor(self, rect: rl.Rectangle, state: BTState) -> None:
    draft = self._draft
    if draft is None:
      return

    # --- fixed header: device name + Back -------------------------------------
    y = rect.y + 20
    name = draft.name or self._selected_address or ''
    gui_label(rl.Rectangle(rect.x, y, rect.width, 70), name, font_size=55, alignment=TextAlignment.CENTER)
    y += 80

    self._back_btn.set_rect(rl.Rectangle(rect.x + self._padding, y, 200, 70))
    self._back_btn.render()

    # Back consumes its own tap while rendering and has already dropped the draft
    # and switched to the list, so stop drawing this frame.
    if self._draft is not draft:
      return

    # --- scrollable body ------------------------------------------------------
    # The mapping grid is taller than the panel on its own; without the scroller
    # the Save / Test row sat below the screen and could never be tapped.
    body_top = y + 90
    scissor_rect = rl.Rectangle(rect.x, body_top, rect.width, max(0.0, (rect.y + rect.height) - body_top))
    offset = self._editor_scroll.update(scissor_rect, rl.Rectangle(rect.x, body_top, rect.width, self._editor_body_height()))

    def clipped(r: rl.Rectangle) -> rl.Rectangle:
      """Restrict a widget's hit area to the visible body, so nothing off-screen
      (or scrolled under the header) can be activated."""
      return rl.get_collision_rec(r, scissor_rect)

    rl.begin_scissor_mode(int(scissor_rect.x), int(scissor_rect.y),
                          int(scissor_rect.width), int(scissor_rect.height))
    y = body_top + offset

    rl.draw_text_ex(gui_app.font(), tr("Profile"), rl.Vector2(rect.x + self._padding, y + 5), 45, 0, rl.Color(200, 200, 200, 255))
    profile_h = 60
    profile_rect = rl.Rectangle(rect.x + 220, y, 380, profile_h)
    rl.draw_rectangle_rounded(profile_rect, 0.3, 10, rl.Color(60, 60, 60, 255))
    rl.draw_text_ex(gui_app.font(), draft.profile, rl.Vector2(profile_rect.x + 15, profile_rect.y + 12), 42, 0, rl.WHITE)
    y += EDITOR_PROFILE_ROW_H

    rl.draw_text_ex(gui_app.font(), tr("Use Carrot mapping"), rl.Vector2(rect.x + self._padding, y + 5), 45, 0, rl.Color(200, 200, 200, 255))
    toggle_x = rect.x + rect.width - 200
    toggle_rect = rl.Rectangle(toggle_x, y, 160, 60)
    toggle_on = draft.enabled
    bg = rl.Color(70, 91, 234, 255) if toggle_on else rl.Color(80, 80, 80, 255)
    rl.draw_rectangle_rounded(toggle_rect, 0.5, 10, bg)
    label = tr("ON") if toggle_on else tr("OFF")
    rl.draw_text_ex(gui_app.font(), label, rl.Vector2(toggle_rect.x + 55, toggle_rect.y + 10), 40, 0, rl.WHITE)
    # Hit test is done by hand here, so clip it to the visible body as well.
    mouse_pos = rl.get_mouse_position()
    if (rl.check_collision_point_rec(mouse_pos, toggle_rect) and rl.check_collision_point_rec(mouse_pos, scissor_rect)
        and rl.is_mouse_button_pressed(rl.MouseButton.MOUSE_BUTTON_LEFT)):
      draft.enabled = not draft.enabled
      self._dirty = True
    y += EDITOR_TOGGLE_ROW_H

    rl.draw_text_ex(gui_app.font(), tr("Button Mapping"), rl.Vector2(rect.x + self._padding, y), 50, 0, rl.WHITE)
    y += EDITOR_HEADING_H

    col_w = self._editor_gesture_col_width(rect)
    col_x = rect.x + self._padding + 150
    for gesture in GESTURES:
      rl.draw_text_ex(gui_app.font(), tr(GESTURE_LABELS.get(gesture, gesture)), rl.Vector2(col_x, y), 38, 0, rl.Color(150, 150, 150, 255))
      col_x += col_w
    y += EDITOR_GESTURE_HEADER_H

    for btn_name in MAPPING_BUTTONS:
      rl.draw_text_ex(gui_app.font(), tr(btn_name), rl.Vector2(rect.x + self._padding, y + 10), 45, 0, rl.WHITE)
      col_x = rect.x + self._padding + 150
      for gesture in GESTURES:
        token = f'{btn_name}_{gesture}'
        action = draft.mapping.get(token, 'none')
        btn = self._gesture_btns[btn_name][gesture]
        btn.set_text(self._action_label(action))
        btn_rect = rl.Rectangle(col_x, y, col_w - 10, EDITOR_ROW_H)
        btn.set_touch_valid_callback(lambda: self._editor_scroll.is_touch_valid())
        btn.set_parent_rect(clipped(btn_rect))
        btn.set_rect(btn_rect)
        btn.render()
        col_x += col_w
      y += EDITOR_ROW_H + EDITOR_ROW_GAP

    y += EDITOR_FOOTER_GAP
    btn_y = y
    gap = 20
    btn_w = (rect.width - self._padding * 2 - gap * 3) // 4
    x = rect.x + self._padding
    self._save_btn.set_rect(rl.Rectangle(x, btn_y, btn_w, EDITOR_FOOTER_H))
    self._save_btn.render()
    x += btn_w + gap

    is_learning = state.learning_addr == self._selected_address
    if is_learning:
      self._stop_btn.set_rect(rl.Rectangle(x, btn_y, btn_w, EDITOR_FOOTER_H))
      self._stop_btn.set_parent_rect(clipped(rl.Rectangle(x, btn_y, btn_w, EDITOR_FOOTER_H)))
      self._stop_btn.render()
    else:
      self._test_btn.set_rect(rl.Rectangle(x, btn_y, btn_w, EDITOR_FOOTER_H))
      self._test_btn.set_parent_rect(clipped(rl.Rectangle(x, btn_y, btn_w, EDITOR_FOOTER_H)))
      self._test_btn.render()
    x += btn_w + gap

    rl.draw_text_ex(gui_app.font(), self._last_event_text[:60], rl.Vector2(x, btn_y + 20), 38, 0, rl.Color(150, 255, 150, 255))

    rl.end_scissor_mode()

  def _render_advanced(self, rect: rl.Rectangle, state: BTState) -> None:
    y = rect.y + 20

    self._back_btn.set_rect(rl.Rectangle(rect.x + self._padding, y, 200, 70))
    self._back_btn.render()
    y += 100

    can_act = state.available
    row_h = 120
    gap = 24

    # Bluetooth master toggle
    y = self._render_advanced_row(
      rect, y, row_h,
      tr("Bluetooth"), tr("Turn Bluetooth radio on or off."),
      self._radio_toggle, state.radio_enabled, can_act, self._on_radio_toggled,
      self._last_radio_state,
    )
    self._last_radio_state = state.radio_enabled
    y += gap

    # Discoverable toggle
    y = self._render_advanced_row(
      rect, y, row_h,
      tr("Discoverable"), tr("Allow other devices to find this device."),
      self._discoverable_toggle, state.discoverable, can_act and state.radio_enabled,
      self._on_discoverable_toggled, self._last_discoverable_state,
    )
    self._last_discoverable_state = state.discoverable
    y += gap + 20

    # Device name
    y = self._render_name_row(rect, y, state, can_act)
    # The name row is two lines tall (title/description, then input + button) where
    # it used to be one, so drop the ad-hoc extra spacing that followed it. Same
    # 24 px rhythm as the toggle rows above, and the page keeps its old footprint.
    y += gap

    # Reset section
    y = self._render_reset_section(rect, y, state, can_act)

  def _render_advanced_row(self, rect: rl.Rectangle, y: float, row_h: float,
                           title: str, desc: str, toggle: Toggle, value: bool,
                           enabled: bool, callback: Callable[[bool], None],
                           last_state: bool) -> float:
    toggle_w, toggle_h = 160, 70
    toggle_rect = rl.Rectangle(rect.x + rect.width - self._padding - toggle_w,
                               y + (row_h - toggle_h) / 2, toggle_w, toggle_h)

    title_rect = rl.Rectangle(rect.x + self._padding, y,
                              rect.width - self._padding * 2 - toggle_w - 20, 50)
    gui_label(title_rect, title, font_size=46, alignment=TextAlignment.LEFT)

    desc_rect = rl.Rectangle(rect.x + self._padding, y + 48,
                             rect.width - self._padding * 2 - toggle_w - 20, 40)
    gui_label(desc_rect, desc, font_size=32, alignment=TextAlignment.LEFT,
              color=rl.Color(170, 170, 170, 255))

    if value != last_state:
      toggle.set_state(value)
    toggle.set_rect(toggle_rect)
    toggle.set_enabled(enabled)
    toggle.render()
    return y + row_h

  def _render_name_row(self, rect: rl.Rectangle, y: float, state: BTState, can_act: bool) -> float:
    # Title + description own the first line, the name input + Edit/Save button the
    # second. They used to share a single 120 px row: the input box was vertically
    # centred (y + 25, 70 tall) while the two labels were drawn from the row top
    # (y and y + 48), so the box background was painted straight over "Device name"
    # and its description - the text and the box visibly overlapped.
    title_h = 50
    desc_h = 40
    box_h = 70
    line_gap = 16

    gui_label(rl.Rectangle(rect.x + self._padding, y, rect.width - self._padding * 2, title_h),
              tr("Device name"), font_size=46, alignment=TextAlignment.LEFT)
    desc_y = y + title_h
    gui_label(rl.Rectangle(rect.x + self._padding, desc_y, rect.width - self._padding * 2, desc_h),
              tr("Name shown to other Bluetooth devices."), font_size=32,
              alignment=TextAlignment.LEFT, color=rl.Color(170, 170, 170, 255))

    input_y = desc_y + desc_h + line_gap
    btn_w = max(160, int(measure_text_cached(gui_app.font(), tr("Save"), 40).x + 50),
                int(measure_text_cached(gui_app.font(), tr("Edit"), 40).x + 50))
    gap = 20
    control_x = rect.x + rect.width - self._padding - btn_w

    # Name value sits to the left of the single action button.
    name_max_w = control_x - gap - (rect.x + self._padding)
    name_rect = rl.Rectangle(rect.x + self._padding, input_y, name_max_w, box_h)
    rl.draw_rectangle_rounded(name_rect, 0.2, 10, rl.Color(50, 50, 50, 255))

    name_text = self._name_input
    name_size = measure_text_cached(gui_app.font(), name_text, 40)
    text_x = name_rect.x + 15
    text_y = name_rect.y + (box_h - name_size.y) / 2
    if name_size.x > name_max_w - 30:
      rl.begin_scissor_mode(int(name_rect.x), int(name_rect.y), int(name_max_w), int(box_h))
      rl.draw_text_ex(gui_app.font(), name_text, rl.Vector2(text_x, text_y), 40, 0, rl.WHITE)
      rl.end_scissor_mode()
    else:
      rl.draw_text_ex(gui_app.font(), name_text, rl.Vector2(text_x, text_y), 40, 0, rl.WHITE)

    # Single button toggles between Edit (name matches saved) and Save (name modified).
    has_changes = self._name_input != state.local_name
    btn_label = tr("Save") if has_changes else tr("Edit")
    btn_style = ButtonStyle.PRIMARY if has_changes else ButtonStyle.NORMAL
    self._name_action_btn.set_text(btn_label)
    self._name_action_btn.set_button_style(btn_style)
    self._name_action_btn.set_rect(rl.Rectangle(control_x, input_y, btn_w, box_h))
    self._name_action_btn.set_enabled(can_act)
    self._name_action_btn.render()

    return input_y + box_h

  def _render_reset_section(self, rect: rl.Rectangle, y: float, state: BTState, can_act: bool) -> float:
    title_h = 60
    gui_label(rl.Rectangle(rect.x + self._padding, y, rect.width - self._padding * 2, title_h),
              tr("Reset Bluetooth"), font_size=44, alignment=TextAlignment.LEFT)
    y += title_h + 10

    gui_label(rl.Rectangle(rect.x + self._padding, y, rect.width - self._padding * 2, 60),
              tr("Remove all pairings and restart the Bluetooth service."), font_size=34,
              alignment=TextAlignment.LEFT, color=rl.Color(170, 170, 170, 255))
    y += 80

    reset_w = min(self._fitted_btn_width(tr("Reset Bluetooth"), 45, 360),
                  int(rect.width - self._padding * 2))
    self._reset_btn.set_rect(rl.Rectangle(rect.x + self._padding, y, reset_w, 90))
    self._reset_btn.set_enabled(can_act)
    self._reset_btn.render()
    return y + 110

  def _action_label(self, action: str) -> str:
    labels = {
      'none': tr('None'),
      'accelCruise': tr('Cruise +'),
      'decelCruise': tr('Cruise −'),
      'accelCruiseLong': tr('Cruise + Long'),
      'decelCruiseLong': tr('Cruise − Long'),
      'gapAdjustCruise': tr('Gap'),
      'lfaButton': tr('LFA'),
      'lfaButtonLong': tr('LFA Long'),
      'cancel': tr('Cancel'),
      'cancelLong': tr('Cancel Long'),
      'laneLeft': tr('Lane Left'),
      'laneRight': tr('Lane Right'),
      'paddleDecel': tr('Paddle −'),
      'carrotCruise': tr('CarrotCruise'),
    }
    return labels.get(action, action)

  def _on_radio_toggled(self, enabled: bool) -> None:
    if enabled == self._state.radio_enabled:
      return
    self._http_async('radio', {'enabled': enabled})

  def _on_discoverable_toggled(self, enabled: bool) -> None:
    self._http_async('discoverable', {'enabled': enabled})

  def _on_scan_clicked(self) -> None:
    with self._state_lock:
      discovering = self._is_scanning_active(self._state)
    if discovering:
      self._scanning_until = 0.0
      self._http_async('cancel')
    else:
      self._scanning_until = time.monotonic() + 32
      self._http_async('scan')

  def _on_advanced_clicked(self) -> None:
    with self._state_lock:
      name = self._state.local_name
    self._name_input = name
    self._panel = BTPanel.ADVANCED

  def _on_install_clicked(self) -> None:
    if self._installing:
      return
    self._installing = True

    def do():
      try:
        result = _http_post('install')
        if result.get('error') and not result.get('ok'):
          with self._state_lock:
            self._error_text = str(result.get('error', 'Unknown error'))
      except Exception as e:
        with self._state_lock:
          self._error_text = str(e)
      finally:
        self._installing = False
        self._fetch_state()
    threading.Thread(target=do, daemon=True).start()

  def _on_enable_service_clicked(self) -> None:
    self._http_async('service', {'start': True})

  def _on_retry_clicked(self) -> None:
    self._fetch_state()

  def _on_edit_clicked(self) -> None:
    pass

  def _on_name_action_clicked(self) -> None:
    with self._state_lock:
      saved_name = self._state.local_name
    if self._name_input != saved_name:
      name = self._name_input.strip()
      if name:
        self._http_async('name', {'name': name})
      return

    def update_name(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._name_input = self._keyboard.text.strip() or self._name_input
    self._keyboard.reset(min_text_size=1)
    self._keyboard.set_title(tr("Device name"), "")
    self._keyboard.set_text(self._name_input)
    self._keyboard.set_callback(update_name)
    gui_app.push_widget(self._keyboard)

  def _on_device_action(self, dev: BTDevice, operation: str) -> None:
    if operation == 'forget':
      self._http_async('forget', {'address': dev.address})
      if self._selected_address == dev.address:
        self._selected_address = None
        self._draft = None
        self._panel = BTPanel.DEVICES
    else:
      self._http_async(operation, {'address': dev.address})

  def _on_row_clicked(self, dev: BTDevice) -> None:
    """Whole-row tap: pair first for an unpaired device, open the editor for a paired one."""
    if not dev.paired:
      self._confirm_pair(dev)
    else:
      self._on_edit_device(dev)

  def _on_edit_device(self, dev: BTDevice) -> None:
    self._selected_address = dev.address
    cfg = self._state.config_devices.get(dev.address)
    if cfg:
      self._draft = BTDevice(
        address=dev.address,
        name=dev.name,
        paired=dev.paired,
        connected=dev.connected,
        profile=cfg.get('profile', 'generic'),
        mapping=cfg.get('mapping', {}),
        enabled=cfg.get('enabled', False),
      )
    else:
      is_yiser = 'yiser-j6' in (dev.name or '').lower()
      self._draft = BTDevice(
        address=dev.address,
        name=dev.name,
        paired=dev.paired,
        connected=dev.connected,
        profile='yiser-j6' if is_yiser else 'generic',
        mapping={**BT_DEFAULTS} if is_yiser else {},
        enabled=False,
      )
    self._dirty = False
    self._panel = BTPanel.EDITOR
    self._last_event_text = ''

  def _on_back_clicked(self) -> None:
    self._panel = BTPanel.DEVICES
    self._draft = None
    self._dirty = False

  def _on_save_clicked(self) -> None:
    if self._draft is None or self._selected_address is None:
      return
    self._http_async('device-config', {
      'address': self._selected_address,
      'device': {
        'name': self._draft.name,
        'profile': self._draft.profile,
        'mapping': self._draft.mapping,
        'enabled': self._draft.enabled,
      }
    })
    self._dirty = False

  def _on_reset_clicked(self) -> None:
    def do():
      try:
        for dev in [d for d in self._state.devices if d.paired]:
          _http_post('forget', {'address': dev.address})
        _http_post('service', {'start': False})
        _http_post('service', {'start': True})
      except Exception as e:
        with self._state_lock:
          self._error_text = str(e)
      self._fetch_state()
    threading.Thread(target=do, daemon=True).start()

  def _on_test_clicked(self) -> None:
    if self._draft is None or self._selected_address is None:
      return
    self._http_async('learn', {'address': self._selected_address, 'enabled': True})

  def _on_stop_clicked(self) -> None:
    self._http_async('learn', {'address': self._selected_address, 'enabled': False})

  def _on_mapping_clicked(self, token: str) -> None:
    if self._draft is None:
      return
    current = self._draft.mapping.get(token, 'none')
    idx = ACTIONS.index(current) if current in ACTIONS else 0
    next_idx = (idx + 1) % len(ACTIONS)
    self._draft.mapping[token] = ACTIONS[next_idx]
    self._dirty = True

  def _http_async(self, operation: str, data: dict | None = None) -> None:
    def do():
      try:
        result = _http_post(operation, data)
        if result.get('error') and not result.get('ok'):
          with self._state_lock:
            self._error_text = str(result.get('error', 'Unknown error'))
      except Exception as e:
        with self._state_lock:
          self._error_text = str(e)
      self._fetch_state()
    threading.Thread(target=do, daemon=True).start()
