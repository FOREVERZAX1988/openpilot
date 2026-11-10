# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Tests for the parked watch daemon.

These lock the fail-closed properties: the daemon must never arm while the
authority inputs are missing, and it must never infer cabin occupancy
(this fork has no cabin camera, and the accelerometer is offroad-unavailable).
"""
import sys
import types
import unittest

if "fcntl" not in sys.modules:
  try:
    import fcntl  # noqa: F401
  except ImportError:
    _fcntl = types.ModuleType("fcntl")
    _fcntl.fcntl = lambda *args, **kwargs: 0
    _fcntl.ioctl = lambda *args, **kwargs: 0
    sys.modules["fcntl"] = _fcntl

# messaging is a compiled Cython extension and does not exist on a Windows
# dev machine. The daemon only needs SubMaster/PubMaster names at import
# time, and the test injects its own fake SubMaster, so a stub keeps the
# module importable off-device. On the device the real module is used.
try:
  import openpilot.common.messaging
except Exception:
  _messaging = types.ModuleType("openpilot.common.messaging")

  class _StubSubMaster:
    def __init__(self, services=None):
      self.services = list(services or [])

    def __getitem__(self, key):
      return None

    def update(self):
      pass

  class _StubPubMaster:
    def __init__(self, services=None):
      self.services = list(services or [])

    def send(self, name, msg):
      pass

  _messaging.SubMaster = _StubSubMaster
  _messaging.PubMaster = _StubPubMaster
  sys.modules["openpilot.common.messaging"] = _messaging

try:
  import openpilot.common.params
except Exception:
  _params_mod = types.ModuleType("openpilot.common.params")

  class _StubParams:
    def __init__(self, *args, **kwargs):
      self.values = {}

    def get(self, key, encoding=None, return_default=False):
      return self.values.get(key, "" if not return_default else None)

    def get_bool(self, key, return_default=False):
      return bool(self.values.get(key, False))

    def put(self, *args, **kwargs):
      pass

    def remove(self, *args, **kwargs):
      pass

  _params_mod.Params = _StubParams
  sys.modules["openpilot.common.params"] = _params_mod

# The offroad alert manager pulls in the cereal/msgq stack, which is a
# compiled extension not present on a dev machine. The alert helper is
# stubbed so the daemon module can be imported; the test asserts on the
# daemon's own decision state, not on the alert side effect.
try:
  import openpilot.selfdrive.selfdrived.alertmanager  # noqa: F401
except Exception:
  _alertmanager = types.ModuleType("openpilot.selfdrive.selfdrived.alertmanager")
  _alertmanager.set_offroad_alert = lambda alert, show_alert, extra_text=None: None
  sys.modules["openpilot.selfdrive.selfdrived.alertmanager"] = _alertmanager

from openpilot.sunnypilot.sentry import sentryd


class FakeParams:
  def __init__(self, enabled=False):
    self._enabled = enabled

  def get_bool(self, key, return_default=False):
    return self._enabled if key == "SentryEnabled" else False

  def get(self, key, encoding=None, return_default=False):
    return ""


class FakeDeviceState:
  def __init__(self, started=False, log_mono_time=1_000_000_000):
    self.started = started
    self.logMonoTime = log_mono_time


class FakePandaState:
  def __init__(self, ignition=False):
    self.ignitionLine = ignition
    self.ignitionCan = ignition


class FakePeripheralState:
  def __init__(self, voltage=12500):
    self.voltage = voltage


class FakeSubMaster:
  def __init__(self, device=None, pandas=None, peripheral=None):
    self.data = {
      "deviceState": device,
      "pandaStates": pandas if pandas is not None else [],
      "peripheralState": peripheral,
    }

  def __getitem__(self, key):
    return self.data.get(key)

  def update(self):
    pass


_UNSET = object()


def make_daemon(*, enabled=True, started=False, ignition=False, voltage=12500,
                device=_UNSET, pandas=_UNSET, peripheral=_UNSET):
  daemon = object.__new__(sentryd.SentryDaemon)
  daemon.params = FakeParams(enabled)
  daemon.sm = FakeSubMaster(
    device=device if device is not _UNSET else FakeDeviceState(started=started),
    pandas=pandas if pandas is not _UNSET else [FakePandaState(ignition=ignition)],
    peripheral=peripheral if peripheral is not _UNSET else FakePeripheralState(voltage=voltage),
  )
  daemon.policy = sentryd.SentryPolicy()
  daemon.last_state_ns = None
  daemon.last_decision = None
  return daemon


class SentryTestCase(unittest.TestCase):
  """Base case that silences cloudlog.

  cloudlog writes to a unix datagram socket, which does not exist on
  Windows. The daemon only logs on state transitions, so the logger is
  replaced for the duration of the test.
  """

  def setUp(self):
    from unittest.mock import patch
    self._cloudlog_patch = patch.object(sentryd, "cloudlog", types.SimpleNamespace(
      info=lambda *a, **k: None, warning=lambda *a, **k: None,
      error=lambda *a, **k: None, event=lambda *a, **k: None,
      debug=lambda *a, **k: None))
    self._cloudlog_patch.start()

  def tearDown(self):
    self._cloudlog_patch.stop()


class TestAuthorityInputs(SentryTestCase):
  def test_ignition_on_means_not_ignition_off(self):
    daemon = make_daemon(ignition=True)
    self.assertFalse(daemon._ignition_off())

  def test_ignition_off_is_detected(self):
    daemon = make_daemon(ignition=False)
    self.assertTrue(daemon._ignition_off())

  def test_any_panda_with_ignition_blocks(self):
    daemon = make_daemon(pandas=[FakePandaState(False), FakePandaState(True)])
    self.assertFalse(daemon._ignition_off())

  def test_low_voltage_is_rejected(self):
    daemon = make_daemon(voltage=11000)
    self.assertFalse(daemon._voltage_ok())

  def test_good_voltage_is_accepted(self):
    daemon = make_daemon(voltage=12500)
    self.assertTrue(daemon._voltage_ok())

  def test_missing_peripheral_state_is_rejected(self):
    daemon = make_daemon(peripheral=None)
    self.assertFalse(daemon._voltage_ok())

  def test_started_device_is_not_offroad(self):
    daemon = make_daemon(started=True)
    self.assertFalse(daemon._offroad())

  def test_stopped_device_is_offroad(self):
    daemon = make_daemon(started=False)
    self.assertTrue(daemon._offroad())


class TestFailClosed(SentryTestCase):
  def test_disabled_feature_never_arms(self):
    daemon = make_daemon(enabled=False)
    for second in range(0, 200, 1):
      daemon.sm.update()
      daemon.step(float(second))
    # Fail-closed: arming never starts while the authority input is missing.
    self.assertIsNone(daemon.policy.arm_started)

  def test_ignition_on_never_arms(self):
    daemon = make_daemon(ignition=True)
    for second in range(0, 200, 1):
      daemon.sm.update()
      daemon.step(float(second))
    # Fail-closed: arming never starts while the authority input is missing.
    self.assertIsNone(daemon.policy.arm_started)

  def test_low_voltage_never_arms(self):
    daemon = make_daemon(voltage=9000)
    for second in range(0, 200, 1):
      daemon.sm.update()
      daemon.step(float(second))
    # Fail-closed: arming never starts while the authority input is missing.
    self.assertIsNone(daemon.policy.arm_started)

  def test_a_stale_device_state_is_not_fresh(self):
    daemon = make_daemon()
    daemon.last_state_ns = int(1e9)
    self.assertFalse(daemon._device_fresh(1_000.0))

  def test_a_fresh_device_state_is_fresh(self):
    daemon = make_daemon()
    daemon.last_state_ns = int(1e9)
    self.assertTrue(daemon._device_fresh(1.0))

  def test_the_first_frame_has_no_device_history(self):
    daemon = make_daemon()
    self.assertFalse(daemon._device_fresh(1.0))


class TestNoOccupancyInference(SentryTestCase):
  def test_the_daemon_never_supplies_a_motion_sample(self):
    """This fork has no cabin camera and no offroad accelerometer.

    The daemon therefore never passes a motion sample to the policy, so the
    detector cannot fire. Any future change that starts supplying samples
    must come with a qualified motion source.
    """
    daemon = make_daemon()
    daemon.sm.update()
    daemon.step(0.0)
    self.assertIsNone(daemon.policy.last_sample_time)


if __name__ == "__main__":
  unittest.main()
