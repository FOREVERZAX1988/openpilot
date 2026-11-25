# Copyright (c) 2026, firestar5683 and StarPilot contributors
# SPDX-License-Identifier: MIT
"""Tests for the sentry notification layer.

Locks the StarPilot semantics: warning/alarm edge-triggering, the
per-kind cooldown, the low_voltage -> battery mapping, retry backoff,
and the unconfigured-channel no-op. The transport is injected, so no
test touches the network.
"""
import sys
import time
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

# Same dev-machine stubs as test_sentryd.py (compiled extensions absent on
# Windows); harmless when the real modules are present.
try:
  import openpilot.common.params  # noqa: F401
except Exception:
  _params_mod = types.ModuleType("openpilot.common.params")

  class _StubParams:
    def __init__(self, *args, **kwargs):
      self.values = {}

    def get(self, key, encoding=None, return_default=False):
      return self.values.get(key, "" if not return_default else None)

    def get_bool(self, key, return_default=False):
      return bool(self.values.get(key, False))

    def put(self, key, value):
      self.values[key] = value

    def remove(self, *args, **kwargs):
      pass

  _params_mod.Params = _StubParams
  sys.modules["openpilot.common.params"] = _params_mod

from openpilot.sunnypilot.sentry import notifications
from openpilot.sunnypilot.sentry.notifications import SentryNotifier, message_text
from openpilot.sunnypilot.sentry.policy import Decision


class FakeParams:
  def __init__(self, values=None):
    self.values = dict(values or {})

  def get(self, key, encoding=None, return_default=False):
    return self.values.get(key, "" if not return_default else None)

  def get_bool(self, key, return_default=False):
    return bool(self.values.get(key, False))

  def put(self, key, value):
    self.values[key] = value

  def remove(self, *args, **kwargs):
    pass


class RecordingTransport:
  def __init__(self, ok=True):
    self.calls = []
    self.ok = ok

  def __call__(self, kind):
    self.calls.append(kind)
    return self.ok


def make_notifier(params=None, transport=None):
  notifier = SentryNotifier(params=params if params is not None else FakeParams(),
                            transport=transport if transport is not None else RecordingTransport())
  notifier._start_worker = lambda: None  # no worker thread in sync tests
  return notifier


class TestMessageText(unittest.TestCase):
  def test_battery_wording_follows_starpilot(self):
    # starpilot notifications.py:44 wording intent.
    self.assertIn("battery is low", message_text("battery").lower())

  def test_motion_wording_includes_kind(self):
    self.assertIn("warning", message_text("warning"))
    self.assertIn("alarm", message_text("alarm"))


class TestKindMapping(unittest.TestCase):
  def setUp(self):
    self.notifier = make_notifier()

  def test_warning_maps_to_warning(self):
    self.assertEqual(self.notifier._kind_for(Decision("armed", event="warning")), "warning")

  def test_alarm_maps_to_alarm(self):
    self.assertEqual(self.notifier._kind_for(Decision("armed", event="alarm")), "alarm")

  def test_low_voltage_entry_maps_to_battery(self):
    self.notifier._last_state = "armed"
    self.assertEqual(self.notifier._kind_for(Decision("low_voltage")), "battery")

  def test_persisting_low_voltage_does_not_renotify(self):
    self.notifier._last_state = "low_voltage"
    self.assertIsNone(self.notifier._kind_for(Decision("low_voltage")))

  def test_plain_states_map_to_nothing(self):
    for state in ("armed", "arming", "disabled", "sensor_unavailable", "unavailable"):
      self.assertIsNone(self.notifier._kind_for(Decision(state)))


class TestCooldown(unittest.TestCase):
  def setUp(self):
    self.transport = RecordingTransport()
    self.notifier = make_notifier(params=FakeParams({"SentryNtfyUrl": "https://ntfy.sh/test"}),
                                  transport=self.transport)

  def test_duplicate_warning_within_cooldown_is_suppressed(self):
    # starpilot policy.py:166-168 fires the alarm once per window; the
    # notifier keeps the same once-per-cooldown guarantee.
    self.notifier.update(100.0, Decision("armed", event="warning"))
    self.notifier.update(110.0, Decision("armed", event="warning"))
    self.assertEqual(len(self.notifier._jobs), 1)

  def test_warning_after_cooldown_is_allowed(self):
    self.notifier.update(100.0, Decision("armed", event="warning"))
    self.notifier.update(100.0 + notifications.MOTION_COOLDOWN_S + 1.0, Decision("armed", event="warning"))
    self.assertEqual(len(self.notifier._jobs), 2)

  def test_battery_transition_notifies_once(self):
    self.notifier.update(0.0, Decision("armed"))
    self.notifier.update(1.0, Decision("low_voltage"))
    self.notifier.update(2.0, Decision("low_voltage"))
    self.assertEqual([job["kind"] for job in self.notifier._jobs], ["battery"])

  def test_no_channel_configured_never_queues(self):
    notifier = make_notifier()  # no params, no subscriptions
    notifier.update(0.0, Decision("armed", event="alarm"))
    self.assertEqual(notifier._jobs, [])


class TestWorker(unittest.TestCase):
  def tearDown(self):
    # Stop any worker started by these tests.
    for notifier in getattr(self, "_notifiers", []):
      notifier.close()
      if notifier._thread is not None:
        notifier._thread.join(timeout=5)

  def _tracked(self, notifier):
    if not hasattr(self, "_notifiers"):
      self._notifiers = []
    self._notifiers.append(notifier)
    return notifier

  def test_job_is_delivered_by_worker(self):
    transport = RecordingTransport(ok=True)
    notifier = self._tracked(SentryNotifier(
      params=FakeParams({"SentryNtfyUrl": "https://ntfy.sh/test"}), transport=transport))
    notifier.update(time.monotonic(), Decision("armed", event="alarm"))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not transport.calls:
      time.sleep(0.05)
    self.assertEqual(transport.calls, ["alarm"])
    self.assertEqual(notifier._jobs, [])

  def test_failed_delivery_is_requeued_with_backoff(self):
    transport = RecordingTransport(ok=False)
    notifier = self._tracked(SentryNotifier(
      params=FakeParams({"SentryNtfyUrl": "https://ntfy.sh/test"}), transport=transport))
    notifier.update(time.monotonic(), Decision("armed", event="warning"))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not transport.calls:
      time.sleep(0.05)
    self.assertEqual(len(transport.calls), 1)
    # StarPilot backoff constants (notifications.py:34-35): first retry after 30s.
    self.assertEqual(len(notifier._jobs), 1)
    job = notifier._jobs[0]
    self.assertEqual(job["attempts"], 1)
    self.assertGreater(job["next"], time.monotonic() + 10)

  def test_all_channels_unconfigured_deliver_returns_false(self):
    notifier = make_notifier()
    self.assertFalse(notifier._deliver("alarm"))


class TestWebhookParams(unittest.TestCase):
  def test_empty_params_mean_disabled(self):
    notifier = make_notifier()
    self.assertIsNone(notifier._send_discord("alarm", "text"))
    self.assertIsNone(notifier._send_ntfy("title", "text"))

  def test_web_push_without_subscriptions_is_unconfigured(self):
    notifier = make_notifier()
    self.assertIsNone(notifier._send_web_push("alarm", "title", "text"))


if __name__ == "__main__":
  unittest.main()
