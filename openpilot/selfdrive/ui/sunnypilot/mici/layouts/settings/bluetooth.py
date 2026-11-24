"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Mici panel for Carrot Bluetooth HID remotes. Reuses the Big GUI panel's HTTP
backend (carrot API on port 7000) and state model so both UIs stay in sync; the
Big GUI layout itself degrades to BigButton lists + pushed sub-pages here.
"""
import threading
import time

from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle, BigToggle, GreyBigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog, BigInputDialog
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.bluetooth_settings import (
  ACTIONS,
  BT_DEFAULTS,
  BTDevice,
  BTState,
  GESTURES,
  MAPPING_BUTTONS,
  _api_path,
  _http_get,
  _http_post,
)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

FETCH_INTERVAL = 1.0
SCAN_WINDOW = 32  # seconds a scan is considered active, same as Big GUI

INFO_ICON = "icons_mici/setup/green_info.png"
WARN_ICON = "icons_mici/setup/red_warning.png"

# Big GUI _action_label, with ASCII hyphens (mici font lacks the U+2212 glyph).
ACTION_LABELS = {
  'none': tr('None'),
  'accelCruise': tr('Cruise +'),
  'decelCruise': tr('Cruise -'),
  'accelCruiseLong': tr('Cruise + Long'),
  'decelCruiseLong': tr('Cruise - Long'),
  'gapAdjustCruise': tr('Gap'),
  'lfaButton': tr('LFA'),
  'lfaButtonLong': tr('LFA Long'),
  'cancel': tr('Cancel'),
  'cancelLong': tr('Cancel Long'),
  'laneLeft': tr('Lane Left'),
  'laneRight': tr('Lane Right'),
  'paddleDecel': tr('Paddle -'),
  'carrotCruise': tr('CarrotCruise'),
}

MAPPING_BUTTON_LABELS = {
  'up': tr('Up'),
  'down': tr('Down'),
  'left': tr('Left'),
  'right': tr('Right'),
  'center': tr('Center'),
  '1': '1',
  '2': '2',
}

GESTURE_LABELS = {
  'single': tr('Short press'),
  'double': tr('Double press'),
  'long': tr('Long press'),
}

PROFILE_OPTIONS = [tr("Generic keyboard / HID"), tr("Yiser-J6")]


class BluetoothLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._lock = threading.Lock()
    self._state = BTState()
    self._error_text = ""
    self._active = False
    self._fetching = False
    self._last_fetch = 0.0
    self._auto_scanned = False
    self._installing = False
    self._scanning_until = 0.0
    self._dismissed_prompt_ids: set[str] = set()
    self._device_sig = None

    self._status_btn = GreyBigButton(tr("Bluetooth"), "")
    self._install_btn = BigButton(tr("Install Bluetooth"), tr("INSTALL"),
                                  description=tr("Install BlueZ to enable Bluetooth HID remotes and device management."))
    self._install_btn.set_click_callback(self._on_install)
    self._enable_btn = BigButton(tr("Enable Bluetooth"), tr("START"),
                                 description=tr("Start the Bluetooth service to scan and pair devices."))
    self._enable_btn.set_click_callback(lambda: self._post_async('service', {'start': True}))
    self._retry_btn = BigButton(tr("Retry"), tr("CHECK"))
    self._retry_btn.set_click_callback(self._fetch_state)
    self._scan_btn = BigButton(tr("Scan"), "", description=tr("Scan for nearby Bluetooth devices."))
    self._scan_btn.set_click_callback(self._on_scan)
    self._advanced_btn = BigButton(tr("Advanced"), "", description=tr("Radio, discoverable, device name and reset."))
    self._advanced_btn.set_click_callback(lambda: gui_app.push_widget(AdvancedPage(self)))

    self._paired_header = GreyBigButton(tr("Paired devices"), "")
    self._available_header = GreyBigButton(tr("Available devices"), "")
    self._no_devices_btn = GreyBigButton("", tr("No devices found"))

    self._device_btns: dict[str, BigButton] = {}

    self._rebuild_items(self._state)

  # ------------------------------------------------------------- state fetch
  def show_event(self):
    super().show_event()
    self._active = True
    self._auto_scanned = False
    self._installing = False
    self._scanning_until = 0.0
    self._dismissed_prompt_ids.clear()
    self._fetch_state()

  def hide_event(self):
    super().hide_event()
    self._active = False

  @property
  def state(self) -> BTState:
    return self._state

  def fetch_if_stale(self):
    """Called by this layout and any pushed sub-page each frame."""
    if not self._active or self._fetching:
      return
    if time.monotonic() - self._last_fetch < FETCH_INTERVAL:
      return
    self._fetching = True
    threading.Thread(target=self._fetch_state, daemon=True).start()

  def _fetch_state(self):
    try:
      data = _http_get(_api_path())
      state = BTState()
      self._parse_state(data, state)
      with self._lock:
        self._state = state
        self._error_text = state.error
    except Exception as exc:
      with self._lock:
        self._error_text = str(exc)
    self._last_fetch = time.monotonic()
    self._fetching = False

  @staticmethod
  def _parse_state(data: dict, state: BTState):
    state.has_bluez = data.get('hasBluez', False)
    state.service_running = data.get('serviceRunning', False)
    state.available = data.get('available', False)
    state.has_uart = data.get('hasUart', False)
    state.has_btpower = data.get('hasBtpower', False)
    state.radio_enabled = data.get('radioEnabled', False)
    state.discoverable = data.get('discoverable', False)
    state.local_name = data.get('localName', '') or ''
    state.error = data.get('error', '') or ''
    state.devices = []
    runtime = data.get('runtime', {})
    for d in data.get('devices', []):
      addr = d.get('address', '')
      cfg = data.get('config', {}).get('devices', {}).get(addr, {})
      state.devices.append(BTDevice(
        address=addr,
        name=d.get('name', addr),
        paired=d.get('paired', False),
        connected=d.get('connected', False),
        rssi=d.get('rssi'),
        battery=d.get('battery'),
        enabled=cfg.get('enabled', False),
        grabbed=addr in runtime.get('grabbed', []),
        profile=cfg.get('profile', 'generic'),
        mapping=cfg.get('mapping', {}),
      ))
    state.config_devices = data.get('config', {}).get('devices', {})
    state.prompt = data.get('prompt')
    state.discovering = any(a.get('discovering', False) for a in data.get('adapters', []))

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
    if state.discovering and time.monotonic() < self._scanning_until:
      return tr("Scanning...")
    if not state.radio_enabled:
      return tr("Bluetooth disabled")
    return tr("Ready")

  @staticmethod
  def _device_status(dev: BTDevice) -> str:
    parts = []
    if dev.connected:
      parts.append(tr("Connected"))
    elif dev.paired:
      parts.append(tr("Paired"))
    if dev.battery is not None:
      parts.append(tr("Battery {}%").format(dev.battery))
    elif dev.rssi is not None:
      parts.append("{} dBm".format(dev.rssi))
    if dev.profile == 'yiser-j6':
      parts.append(tr("Mapping on") if dev.enabled else tr("Mapping off"))
    return " · ".join(parts)

  def current_device(self, addr: str) -> BTDevice | None:
    return next((d for d in self._state.devices if d.address == addr), None)

  # ----------------------------------------------------------------- actions
  def _post_async(self, operation: str, data: dict | None = None):
    def do():
      try:
        result = _http_post(operation, data)
        if result.get('error') and not result.get('ok'):
          with self._lock:
            self._error_text = str(result.get('error', 'Unknown error'))
      except Exception as exc:
        with self._lock:
          self._error_text = str(exc)
      self._last_fetch = 0.0  # refresh immediately
    threading.Thread(target=do, daemon=True).start()

  def _on_install(self):
    if self._installing:
      return
    self._installing = True

    def do():
      try:
        result = _http_post('install')
        if result.get('error') and not result.get('ok'):
          with self._lock:
            self._error_text = str(result.get('error', 'Unknown error'))
      except Exception as exc:
        with self._lock:
          self._error_text = str(exc)
      finally:
        self._installing = False
        self._last_fetch = 0.0
    threading.Thread(target=do, daemon=True).start()

  def _on_scan(self):
    if self._state.discovering and time.monotonic() < self._scanning_until:
      self._scanning_until = 0.0
      self._post_async('cancel')
    else:
      self._scanning_until = time.monotonic() + SCAN_WINDOW
      self._post_async('scan')

  def _on_device_clicked(self, addr: str):
    dev = self.current_device(addr)
    if dev is None:
      return
    if not dev.paired:
      name = dev.name or dev.address

      def on_confirm():
        self._scanning_until = time.monotonic() + SCAN_WINDOW
        self._post_async('pair', {'address': dev.address})
      gui_app.push_widget(BigConfirmationDialog(tr('Pair with "{}"?').format(name),
                                                gui_app.texture(INFO_ICON, 64, 64), on_confirm))
    else:
      gui_app.push_widget(DevicePage(self, addr))

  def _on_reset_confirmed(self):
    def do():
      try:
        for dev in [d for d in self._state.devices if d.paired]:
          _http_post('forget', {'address': dev.address})
        _http_post('service', {'start': False})
        _http_post('service', {'start': True})
      except Exception as exc:
        with self._lock:
          self._error_text = str(exc)
      self._last_fetch = 0.0
    threading.Thread(target=do, daemon=True).start()

  # ------------------------------------------------------------ prompt flow
  def _answer(self, pid: str, value):
    self._post_async('answer', {'id': pid, 'value': value})

  def _handle_prompt(self, state: BTState):
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
      gui_app.push_widget(BigDialog(tr("Pairing code: {}").format(value), ""))
      return

    if kind in ('RequestConfirmation', 'RequestAuthorization', 'AuthorizeService'):
      def on_confirm():
        self._answer(pid, True)
      dlg = BigConfirmationDialog(tr("Confirm pairing with \"{}\"?").format(value),
                                  gui_app.texture(INFO_ICON, 64, 64), on_confirm)
      # unlike Big GUI's ConfirmDialog, cancel/dismiss doesn't fire the callback;
      # answer False on hide so the daemon doesn't keep the prompt pending forever.
      answered = []

      def on_hidden():
        if not answered:
          self._answer(pid, False)
      orig_confirm = dlg._confirm_callback

      def confirm_wrapper():
        answered.append(True)
        orig_confirm()
      dlg._confirm_callback = confirm_wrapper
      orig_hidden = dlg.hide_event
      dlg.hide_event = lambda: (on_hidden(), orig_hidden())
      gui_app.push_widget(dlg)
      return

    if kind in ('RequestPinCode', 'RequestPasskey'):
      is_passkey = kind == 'RequestPasskey'
      gui_app.push_widget(BigInputDialog(
        tr("Enter passkey") if is_passkey else tr("Enter PIN"),
        "",
        minimum_length=1,
        text_validator=(lambda text: text.isdigit()) if is_passkey else None,
        confirm_callback=lambda text: self._answer(pid, text),
      ))

  # ------------------------------------------------------------ list layout
  def _device_button(self, addr: str) -> BigButton:
    btn = self._device_btns.get(addr)
    if btn is None:
      btn = BigButton("", "", scroll=True)
      btn.set_click_callback(lambda a=addr: self._on_device_clicked(a))
      self._device_btns[addr] = btn
    return btn

  def _rebuild_items(self, state: BTState):
    widgets = [self._status_btn]

    if not state.has_bluez:
      widgets.append(self._install_btn)
    elif not state.service_running:
      widgets.append(self._enable_btn)
    elif not state.available:
      widgets.append(self._retry_btn)
    elif state.radio_enabled:
      widgets.append(self._scan_btn)

    if state.available and state.radio_enabled:
      paired = [d for d in state.devices if d.paired]
      available = [d for d in state.devices if not d.paired]
      if paired:
        widgets.append(self._paired_header)
        widgets.extend(self._device_button(d.address) for d in paired)
      if available:
        widgets.append(self._available_header)
        widgets.extend(self._device_button(d.address) for d in available)
      if not state.devices:
        widgets.append(self._no_devices_btn)

    widgets.append(self._advanced_btn)

    self._scroller.items.clear()
    self._scroller.add_widgets(widgets)

  # ------------------------------------------------------------------ update
  def _update_state(self):
    super()._update_state()

    self.fetch_if_stale()

    with self._lock:
      state = self._state
      error = self._error_text

    status = self._status_for_state(state)
    self._status_btn.set_value(error or status)

    if self._auto_scanned is False and state.available and state.radio_enabled:
      self._auto_scanned = True
      self._scanning_until = time.monotonic() + SCAN_WINDOW
      self._post_async('scan')

    scanning = state.discovering and time.monotonic() < self._scanning_until
    self._scan_btn.set_text(tr("Stop") if scanning else tr("Scan"))
    self._install_btn.set_value(tr("Installing...") if self._installing else tr("INSTALL"))

    # rebuild rows only when the device set changes; refresh values in place otherwise
    sig = tuple((d.address, d.name, d.paired) for d in state.devices) + \
          (state.has_bluez, state.service_running, state.available, state.radio_enabled)
    if sig != self._device_sig:
      self._device_sig = sig
      self._rebuild_items(state)

    for dev in state.devices:
      btn = self._device_btns.get(dev.address)
      if btn is not None:
        btn.set_text(dev.name or dev.address)
        btn.set_value(self._device_status(dev))

    self._handle_prompt(state)


class DevicePage(NavScroller):
  def __init__(self, layout: BluetoothLayoutMici, addr: str):
    super().__init__()
    self._bt_layout = layout
    self._addr = addr

    dev = layout.current_device(addr)
    name = (dev.name if dev else '') or addr

    self._info_btn = GreyBigButton(name, "")
    self._connect_btn = BigButton(tr("Disconnect") if dev and dev.connected else tr("Connect"), "",
                                  description=tr("Open or close the HID connection to this device."))
    self._connect_btn.set_click_callback(self._on_connect)
    self._edit_btn = BigButton(tr("Edit"), tr("MAPPING"),
                               description=tr("Profile, Carrot mapping and per-button actions."))
    self._edit_btn.set_click_callback(self._on_edit)
    self._forget_btn = BigButton(tr("Forget"), tr("FORGET"),
                                 description=tr('Forget "{}"?').format(name))
    self._forget_btn.set_click_callback(self._on_forget)

    self._scroller.add_widgets([self._info_btn, self._connect_btn, self._edit_btn, self._forget_btn])

  def _update_state(self):
    super()._update_state()
    self._bt_layout.fetch_if_stale()

    dev = self._bt_layout.current_device(self._addr)
    if dev is None:
      return
    self._info_btn.set_value(self._bt_layout._device_status(dev))
    self._connect_btn.set_text(tr("Disconnect") if dev.connected else tr("Connect"))

  def _on_connect(self):
    dev = self._bt_layout.current_device(self._addr)
    if dev is None:
      return
    self._bt_layout._post_async('disconnect' if dev.connected else 'connect', {'address': dev.address})

  def _on_edit(self):
    gui_app.push_widget(EditorPage(self._bt_layout, self._addr))

  def _on_forget(self):
    dev = self._bt_layout.current_device(self._addr)
    if dev is None:
      return
    name = dev.name or dev.address

    def on_confirm():
      self._bt_layout._post_async('forget', {'address': dev.address})
      gui_app.pop_widget()
    gui_app.push_widget(BigConfirmationDialog(tr('Forget "{}"?').format(name),
                                              gui_app.texture(WARN_ICON, 64, 64), on_confirm, red=True))


class EditorPage(NavScroller):
  """Per-device editor: profile, Carrot-mapping toggle, per-button mapping, save."""

  def __init__(self, layout: BluetoothLayoutMici, addr: str):
    super().__init__()
    self._bt_layout = layout
    self._addr = addr

    dev = layout.current_device(addr)
    cfg = layout.state.config_devices.get(addr, {})
    is_yiser = 'yiser-j6' in ((dev.name if dev else '') or '').lower()
    self._device_name = (dev.name if dev else '') or addr
    self._profile = cfg.get('profile', 'yiser-j6' if is_yiser else 'generic')
    self._mapping = dict(cfg.get('mapping', {})) if cfg else ({**BT_DEFAULTS} if is_yiser else {})
    self._enabled = bool(cfg.get('enabled', False))

    self._mapping_rows: dict[str, BigButton] = {}

    self._profile_toggle = BigMultiToggle(tr("Profile"), PROFILE_OPTIONS, select_callback=self._on_profile)
    self._profile_toggle.set_value(PROFILE_OPTIONS[1] if self._profile == 'yiser-j6' else PROFILE_OPTIONS[0])

    self._enabled_toggle = BigToggle(tr("Use Carrot mapping"), "", initial_state=self._enabled,
                                     toggle_callback=lambda checked: setattr(self, '_enabled', checked))
    self._save_btn = BigButton(tr("Save"), tr("SAVE"), description=tr("Store this device's profile and mapping."))
    self._save_btn.set_click_callback(self._on_save)
    self._learn_btn = BigButton(tr("Test / Learn"), tr("START"),
                                description=tr("Capture this remote's events to verify the mapping."))
    self._learn_btn.set_click_callback(lambda: self._bt_layout._post_async('learn', {'address': self._addr, 'enabled': True}))
    self._stop_btn = BigButton(tr("Stop Test"), tr("STOP"))
    self._stop_btn.set_click_callback(lambda: self._bt_layout._post_async('learn', {'address': self._addr, 'enabled': False}))

    widgets: list = [
      GreyBigButton(self._device_name, tr("Button Mapping")),
      self._profile_toggle,
      self._enabled_toggle,
    ]
    for btn_name in MAPPING_BUTTONS:
      widgets.append(GreyBigButton(MAPPING_BUTTON_LABELS[btn_name], ""))
      for gesture in GESTURES:
        token = f'{btn_name}_{gesture}'
        row = BigButton(GESTURE_LABELS[gesture], "", scroll=True)
        row.set_click_callback(lambda t=token: gui_app.push_widget(ActionPickerPage(self, t)))
        self._mapping_rows[token] = row
        widgets.append(row)
    widgets.extend([self._save_btn, self._learn_btn, self._stop_btn])
    self._scroller.add_widgets(widgets)

  def _on_profile(self, value: str):
    self._profile = 'yiser-j6' if value == PROFILE_OPTIONS[1] else 'generic'
    # same preset semantics as Big GUI: Yiser-J6 starts from the default mapping
    self._mapping = {**BT_DEFAULTS} if self._profile == 'yiser-j6' else {}

  def _update_state(self):
    super()._update_state()
    self._bt_layout.fetch_if_stale()
    for token, row in self._mapping_rows.items():
      row.set_value(ACTION_LABELS.get(self._mapping.get(token, 'none'), tr('None')))

  def _on_save(self):
    self._bt_layout._post_async('device-config', {
      'address': self._addr,
      'device': {
        'name': self._device_name,
        'profile': self._profile,
        'mapping': self._mapping,
        'enabled': self._enabled,
      },
    })


class ActionPickerPage(NavScroller):
  def __init__(self, editor: EditorPage, token: str):
    super().__init__()
    self._editor = editor
    self._token = token

    btn_name, gesture = token.rsplit('_', 1)
    title = f"{MAPPING_BUTTON_LABELS.get(btn_name, btn_name)} · {GESTURE_LABELS.get(gesture, gesture)}"
    current = editor._mapping.get(token, 'none')

    self._scroller.add_widget(GreyBigButton(title, tr("Select the action for this press:")))
    for action in ACTIONS:
      btn = BigButton(ACTION_LABELS[action], tr("selected") if action == current else "", scroll=True)
      btn.set_click_callback(lambda a=action: self._pick(a))
      self._scroller.add_widget(btn)

  def _pick(self, action: str):
    self._editor._mapping[self._token] = action
    gui_app.pop_widget()


class AdvancedPage(NavScroller):
  def __init__(self, layout: BluetoothLayoutMici):
    super().__init__()
    self._bt_layout = layout
    # optimistic values until the daemon state catches up with the POST
    self._pending: dict[str, bool] = {}

    self._radio_toggle = BigToggle(tr("Bluetooth"), "", initial_state=layout.state.radio_enabled,
                                   toggle_callback=self._on_radio,
                                   description=tr("Turn Bluetooth radio on or off."))
    self._discoverable_toggle = BigToggle(tr("Discoverable"), "", initial_state=layout.state.discoverable,
                                          toggle_callback=self._on_discoverable,
                                          description=tr("Allow other devices to find this device."))
    self._name_btn = BigButton(tr("Device name"), layout.state.local_name,
                               description=tr("Name shown to other Bluetooth devices."))
    self._name_btn.set_click_callback(self._on_name)
    self._reset_btn = BigButton(tr("Reset Bluetooth"), tr("RESET"),
                                description=tr("Remove all pairings and restart the Bluetooth service."))
    self._reset_btn.set_click_callback(self._on_reset)

    self._scroller.add_widgets([
      self._radio_toggle,
      self._discoverable_toggle,
      self._name_btn,
      self._reset_btn,
    ])

  def _sync_toggle(self, toggle: BigToggle, key: str, state_value: bool):
    if key in self._pending:
      if self._pending[key] == state_value:
        del self._pending[key]
      else:
        toggle.set_checked(self._pending[key])
        return
    toggle.set_checked(state_value)

  def _update_state(self):
    super()._update_state()
    self._bt_layout.fetch_if_stale()

    state = self._bt_layout.state
    self._sync_toggle(self._radio_toggle, 'radio', state.radio_enabled)
    self._sync_toggle(self._discoverable_toggle, 'discoverable', state.discoverable)
    self._name_btn.set_value(state.local_name)

  def _on_radio(self, checked: bool):
    self._pending['radio'] = checked
    self._bt_layout._post_async('radio', {'enabled': checked})

  def _on_discoverable(self, checked: bool):
    self._pending['discoverable'] = checked
    self._bt_layout._post_async('discoverable', {'enabled': checked})

  def _on_name(self):
    current = self._bt_layout.state.local_name
    gui_app.push_widget(BigInputDialog(
      tr("Device name"),
      current,
      minimum_length=1,
      confirm_callback=lambda text: self._bt_layout._post_async('name', {'name': text.strip()}),
    ))

  def _on_reset(self):
    gui_app.push_widget(BigConfirmationDialog(
      tr("Reset Bluetooth"),
      gui_app.texture(WARN_ICON, 64, 64),
      self._bt_layout._on_reset_confirmed,
      red=True,
    ))
