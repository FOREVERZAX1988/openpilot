"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Carrot tuning eGPU / Chestnut status page for mici.

Port of the Big GUI ``carrot_tuning_egpu.py`` EgpuPanelWidget, degraded to the
mici widget set: the custom-rendered status card becomes a page of status
rows (GreyBigButton header + disabled BigButton label/value rows), keeping the
same webui-style state mapping, texts and not-detected warning.
"""
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

try:
  from openpilot.selfdrive.ui.ui_state import ChestnutState
except ImportError:
  # Fallback for test environments that mock ui_state without the enum.
  from enum import Enum
  class ChestnutState(Enum):  # type: ignore[no-redef]
    DISCONNECTED = "disconnected"
    UNCOMPILED = "uncompiled"
    READY = "ready"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"

# webui-style state key per ChestnutState (same mapping as Big GUI).
_STATE_KEYS = {
  ChestnutState.DISCONNECTED: 'gray',
  ChestnutState.UNCOMPILED: 'failed',
  ChestnutState.READY: 'gray',
  ChestnutState.LOADING: 'loading',
  ChestnutState.ACTIVE: 'green',
  ChestnutState.FAILED: 'failed',
}


class EgpuPageMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._header_btn = GreyBigButton(tr("eGPU / Big Model"), "")
    self._warning_btn = GreyBigButton("", tr("eGPU (Chestnut) not detected. Connect your eGPU hardware to enable."))

    self._state_btn = BigButton(tr("Current State"), "")
    self._state_btn.set_enabled(False)
    self._available_btn = BigButton(tr("eGPU Available"), "")
    self._available_btn.set_enabled(False)
    self._desc_btn = BigButton(tr("Description"), "")
    self._desc_btn.set_enabled(False)

    self._scroller.add_widgets([
      self._header_btn,
      self._warning_btn,
      self._state_btn,
      self._available_btn,
      self._desc_btn,
    ])

  # ------------------------------------------------------------------ helpers
  def _chestnut_state_key(self) -> tuple[bool, str]:
    """Return (present, webui-style state key) for the current ui_state."""
    present = bool(ui_state.chestnut_present) if hasattr(ui_state, 'chestnut_present') else False
    if not present:
      return False, 'gray'
    return True, _STATE_KEYS.get(ui_state.chestnut_state, 'gray')

  @staticmethod
  def _state_label(state: str) -> str:
    return {
      'gray': tr("eGPU Not Active"),
      'green': tr("eGPU Active"),
      'failed': tr("eGPU Failed"),
      'loading': tr("eGPU Loading..."),
    }.get(state, state)

  @staticmethod
  def _state_desc(state: str) -> str:
    return {
      'gray': tr("No eGPU (big model) is selected. The default model is running."),
      'green': tr("eGPU big model is running and healthy."),
      'failed': tr("eGPU was selected but failed to start. Check device connection and model files."),
      'loading': tr("eGPU big model is being loaded. This may take a moment."),
    }.get(state, "")

  # ------------------------------------------------------------------- update
  def _update_state(self):
    super()._update_state()

    present, state = self._chestnut_state_key()
    label = self._state_label(state)
    desc = self._state_desc(state)

    self._header_btn.set_value(label)
    self._warning_btn.set_visible(not present)
    self._state_btn.set_value(label)
    self._available_btn.set_value(tr("Yes") if present else tr("No"))
    self._desc_btn.set_value(desc)
