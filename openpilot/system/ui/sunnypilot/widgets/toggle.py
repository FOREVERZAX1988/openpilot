"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import time
from collections.abc import Callable

import pyray as rl
from openpilot.sunnypilot.carrot.config import unified_params
from openpilot.system.ui.lib.application import MousePos
from openpilot.system.ui.widgets.toggle import Toggle
from openpilot.system.ui.sunnypilot.lib.styles import style

KNOB_PADDING = 5
KNOB_RADIUS = style.TOGGLE_BG_HEIGHT / 2 - KNOB_PADDING

# How often a bound toggle re-reads the store while it is on screen. The settings UI and
# the web panel write the same store, so a value the other surface just changed has to
# turn up here without the driver leaving and re-entering the page. Twice a second reads
# as instant and keeps the render path from becoming a per-frame Params reader.
SYNC_INTERVAL = 0.5

# A Params write is asynchronous: a read taken straight after one still returns the old
# value. A write this widget made therefore stays authoritative on screen until the store
# echoes it back, so a poll cannot undo the driver's tap.
PENDING_WRITE_TIMEOUT = 1.0


class ToggleSP(Toggle):
  """A toggle bound to a parameter, kept in step with whatever wrote it last.

  ``param`` is a key this widget owns: it writes on tap and re-reads on a timer.
  ``sync_param`` is a key it only mirrors, for the cases where the write is not a plain
  param put -- Experimental Mode opens a confirmation dialog, so its callback owns the
  write and the switch still follows the store. Either way a change made from the web
  panel (or from the driving code) shows up within SYNC_INTERVAL instead of waiting for
  the next offroad/engaged transition, which is what made the two surfaces disagree while
  the store already held the new value.
  """

  def __init__(self, initial_state=False, callback: Callable[[bool], None] | None = None, param: str | None = None,
               sync_param: str | None = None):
    self.param_key = param
    self.sync_param_key = param if sync_param is None else sync_param
    self.params = unified_params
    self._pending_state: bool | None = None
    self._pending_until = 0.0
    self._next_sync = 0.0
    self._sync_paused = False
    if self.sync_param_key:
      initial_state = self.params.get_bool(self.sync_param_key)
    Toggle.__init__(self, initial_state, callback)

  def set_sync_paused(self, paused: bool) -> None:
    """Stop adopting the store, e.g. while a confirmation dialog owns this switch."""
    self._sync_paused = paused
    if not paused:
      self._next_sync = 0.0

  def sync(self, now: float | None = None) -> bool:
    """Take the stored value if another surface wrote it. True when the switch moved."""
    if not self.sync_param_key or self._sync_paused:
      return False
    now = time.monotonic() if now is None else now
    if now < self._next_sync:
      return False
    self._next_sync = now + SYNC_INTERVAL

    stored = self.params.get_bool(self.sync_param_key)
    if self._pending_state is not None:
      if stored == self._pending_state:
        self._pending_state = None
      elif now < self._pending_until:
        return False
      else:
        self._pending_state = None

    if stored != self._state:
      self.set_state(stored)
      return True
    return False

  def set_rect(self, rect: rl.Rectangle):
    self._rect = rl.Rectangle(rect.x, rect.y, style.TOGGLE_WIDTH, style.TOGGLE_HEIGHT)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    if not self._enabled:
      return
    if self.param_key:
      self.params.put_bool(self.param_key, self._state)
    if self.sync_param_key:
      # hold the tapped state until the store shows it (a callback-owned write takes a
      # dialog, and its own put lands later still)
      self._pending_state = self._state
      self._pending_until = time.monotonic() + PENDING_WRITE_TIMEOUT

  def _render(self, rect: rl.Rectangle):
    self.sync()
    self.update()
    self._rect.y -= style.ITEM_PADDING / 2
    if self._enabled:
      bg_color = self._blend_color(style.TOGGLE_OFF_COLOR, style.TOGGLE_ON_COLOR, self._progress)
      knob_color = style.TOGGLE_KNOB_COLOR
    else:
      bg_color = self._blend_color(style.TOGGLE_DISABLED_OFF_COLOR, style.TOGGLE_DISABLED_ON_COLOR, self._progress)
      knob_color = style.TOGGLE_DISABLED_KNOB_COLOR

    # Draw background
    bg_rect = rl.Rectangle(self._rect.x, self._rect.y, style.TOGGLE_WIDTH, style.TOGGLE_BG_HEIGHT)

    # Draw actual background
    rl.draw_rectangle_rounded(bg_rect, 1.0, 10, bg_color)

    left_edge = bg_rect.x + KNOB_PADDING
    right_edge = bg_rect.x + bg_rect.width - KNOB_PADDING

    knob_travel_distance = right_edge - left_edge - 2 * KNOB_RADIUS
    min_knob_x = left_edge + KNOB_RADIUS
    knob_x = min_knob_x + knob_travel_distance * self._progress
    knob_y = self._rect.y + style.TOGGLE_BG_HEIGHT / 2

    rl.draw_circle(int(knob_x), int(knob_y), KNOB_RADIUS, knob_color)

    clicked = self._clicked
    self._clicked = False
    return clicked
