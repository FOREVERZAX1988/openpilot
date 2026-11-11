"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Helpers the tici and mici settings tests share. ``gui`` and ``params`` are
module-level fixtures resolved by OpenpilotTestCase when a test method names
them; import them into the test module so the lookup finds them.
"""

_GUI_APP = None


def gui():
  """A hidden raylib window, created once per process: widgets need textures.
  A module picks the big or the mici UI by setting BIG before its imports; the
  window itself is shared."""
  global _GUI_APP
  if _GUI_APP is None:
    import atexit
    import raylib_nb as rl
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
    from openpilot.system.ui.lib.application import gui_app
    gui_app.init_window("ui-tests", fps=30)
    _GUI_APP = gui_app
    atexit.register(gui_app.close)
  return _GUI_APP


def params(gui):
  """Isolated params for the UI, in the shared window."""
  from openpilot.common.params import Params
  from openpilot.selfdrive.ui.ui_state import ui_state

  p = Params()
  ui_state.params = p
  # on device update_params() runs every frame before anything draws, so attributes it
  # sets (always_offroad, screensaver_enabled, ...) exist by render time. Without this a
  # layout reading one of them fails in the test for a reason the device never sees.
  ui_state.update_params()
  return p


def wait_until(condition, timeout: float = 2.0):
  """The panels write with a non-blocking put(), which lands on a background thread."""
  import time
  deadline = time.monotonic() + timeout
  while not condition():
    assert time.monotonic() < deadline, "timed out"
    time.sleep(0.005)


def render(widget, width: int = 800, height: int = 600):
  """Drive one frame through Widget.render, which calls _update_state."""
  import raylib_nb as rl
  return widget.render(rl.Rectangle(0, 0, width, height))


def jetlink_status(**fields):
  """jetlink's snapshot as the UI's params pass takes it, nothing to show unless
  a field says so. A link turned on reads as USB unless the mode is given."""
  from jetlink.openpilot import Status
  base = {'enabled': False, 'mode': 'usb' if fields.get('enabled') else 'off', 'transport': 'USB', 'present': False,
          'port': None, 'ready': False, 'reason': None, 'progress': None, 'model': None, 'default_model': None}
  return Status(**{**base, **fields})
