"""Tests for GuiApplication._watch_for_render_stall.

The freeze this guards against leaves the process alive with a fresh
kick_watchdog() heartbeat, which is why neither restart_if_crash nor the
manager watchdog can see it: the panel keeps the last frame it swapped and
everything outside the render loop still looks healthy. These tests pin the
three ways the stall clock can be read -- a loop that was healthy and then
stopped drawing must exit so restart_if_crash brings it back, a loop that was
never healthy (a slow first boot) must be left alone, and a loop that recovers
must not carry the old timer into the next stall.
"""
import unittest

from openpilot.common.test import Mocker, OpenpilotTestCase
from openpilot.system.ui.lib import application
from openpilot.system.ui.lib.application import FPS_STALL_DUMP_S, GuiApplication


class _Clock:
  def __init__(self):
    self.now = 1000.0

  def monotonic(self) -> float:
    return self.now

  def advance(self, dt: float) -> None:
    self.now += dt


class TestRenderStall(OpenpilotTestCase):
  TARGET_FPS = 20

  def _make_app(self, mocker: Mocker) -> tuple[GuiApplication, _Clock]:
    clock = _Clock()
    app = GuiApplication.__new__(GuiApplication)
    app._target_fps = self.TARGET_FPS
    app._render_stall_since = None
    app._fps_healthy = False
    app._frame = 0
    app._should_render = True
    app._scale = 1.0
    app.close_ffmpeg = mocker.MagicMock()
    app._dump_stall_stacks = mocker.MagicMock(return_value='/tmp/ui_render_stall.log')
    mocker.patch.object(application.time, 'monotonic', clock.monotonic)
    mocker.patch.object(application.os, '_exit', mocker.MagicMock())
    return app, clock

  def _run_for(self, app, clock: _Clock, fps: float, seconds: float) -> None:
    """Hold the given frame rate for a stretch of wall clock, one second at a time."""
    for _ in range(int(seconds)):
      clock.advance(1.0)
      app._watch_for_render_stall(fps)

  def test_healthy_then_frozen_restarts(self, mocker: Mocker):
    app, clock = self._make_app(mocker)
    app._watch_for_render_stall(self.TARGET_FPS)
    self.assertTrue(app._fps_healthy)

    self._run_for(app, clock, 0, FPS_STALL_DUMP_S - 1)
    application.os._exit.assert_not_called()

    self._run_for(app, clock, 0, 2)
    application.os._exit.assert_called_once_with(1)
    app._dump_stall_stacks.assert_called_once()

  def test_boot_that_never_reached_target_is_not_killed(self, mocker: Mocker):
    """A first boot baking fonts and loading models is slow, not frozen."""
    app, clock = self._make_app(mocker)
    self._run_for(app, clock, 0, FPS_STALL_DUMP_S * 4)
    application.os._exit.assert_not_called()
    app._dump_stall_stacks.assert_not_called()

  def test_recovery_clears_the_stall_clock(self, mocker):
    app, clock = self._make_app(mocker)
    app._watch_for_render_stall(self.TARGET_FPS)

    self._run_for(app, clock, 0, FPS_STALL_DUMP_S - 2)
    app._watch_for_render_stall(self.TARGET_FPS)
    self.assertIsNone(app._render_stall_since)

    self._run_for(app, clock, 0, FPS_STALL_DUMP_S - 2)
    application.os._exit.assert_not_called()

  def test_slow_but_not_frozen_is_left_alone(self, mocker: Mocker):
    app, clock = self._make_app(mocker)
    app._watch_for_render_stall(self.TARGET_FPS)
    slow = self.TARGET_FPS * 0.75
    self._run_for(app, clock, slow, FPS_STALL_DUMP_S * 4)
    application.os._exit.assert_not_called()


if __name__ == '__main__':
  unittest.main()
