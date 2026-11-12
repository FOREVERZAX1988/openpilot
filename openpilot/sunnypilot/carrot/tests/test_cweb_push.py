"""CWeb push reporter tests (PC-runnable, no network).

PYTHONPATH="/data/openpilot" python -m unittest openpilot.sunnypilot.carrot.tests.test_cweb_push
"""
import os
import sys
import types
import unittest
from unittest import mock

if 'fcntl' not in sys.modules or not hasattr(sys.modules.get('fcntl'), 'flock'):
  _fcntl = types.ModuleType('fcntl')
  for name in ('flock', 'lockf', 'ioctl'):
    setattr(_fcntl, name, lambda *a, **k: None)
  _fcntl.LOCK_EX, _fcntl.LOCK_SH, _fcntl.LOCK_UN, _fcntl.LOCK_NB = 2, 1, 8, 4
  sys.modules['fcntl'] = _fcntl

# PC stub: the native libparams backend cannot load on Windows. The reporter
# only exercises get/put through the Params facade, so a dict store is enough.
try:
  from openpilot.common.params import Params
except (OSError, ModuleNotFoundError):
  # PC: no native libparams. Use the shared stub so every suite in a combined
  # unittest run sees identical Params behavior regardless of load order.
  from openpilot.common.tests import params_pc_stub
  params_pc_stub.register()
  Params = params_pc_stub.Params
from openpilot.sunnypilot.carrot.cweb_push import (
  CwebPushReporter, build_payload, device_id, resolve_report_url,
)


class TestResolveReportUrl(unittest.TestCase):
  def setUp(self):
    os.environ.pop("CWEB_PUSH_REPORT_URL", None)
    try:
      Params().remove("CwebPushReportUrl")
    except Exception:
      pass

  def test_env_wins(self):
    os.environ["CWEB_PUSH_REPORT_URL"] = "http://10.0.0.5:8080/report"
    self.assertEqual(resolve_report_url(Params()), "http://10.0.0.5:8080/report")

  def test_param_used_when_no_env(self):
    Params().put("CwebPushReportUrl", "http://192.168.1.9:8080/report")
    self.assertEqual(resolve_report_url(Params()), "http://192.168.1.9:8080/report")

  def test_unconfigured_is_empty_not_a_third_party_url(self):
    """Privacy contract: with nothing configured the fork must NOT phone any
    baked-in endpoint (cp XOR-obfuscated its operator's relay; the table here
    is deliberately empty)."""
    self.assertEqual(resolve_report_url(Params()), "")


class TestReporter(unittest.TestCase):
  def _reporter(self, **kw):
    defaults = {
      'params': Params(), 'report_url': 'http://example.test/report',
      'heartbeat_url': 'http://example.test/heartbeat', 'iface': 'wlan0', 'port': 7000,
      'timeout_s': 1.0, 'heartbeat_interval_s': 5.0, 'debounce_s': 0.0,
    }
    defaults.update(kw)
    return CwebPushReporter(**defaults)

  def test_stable_ip_reports_once_then_heartbeats(self):
    r = self._reporter()
    with mock.patch("openpilot.sunnypilot.carrot.cweb_push.get_local_ip", return_value="192.168.7.229"), \
         mock.patch("openpilot.sunnypilot.carrot.cweb_push.post_json", return_value=(True, 200, "ok")) as post:
      self.assertFalse(r.poll_once())  # frame 1: ip candidate only
      self.assertTrue(r.poll_once())   # frame 2: stable -> first report
      self.assertEqual(post.call_count, 1)
      self.assertEqual(post.call_args[0][0], "http://example.test/report")
      r.next_heartbeat_at = 0.0
      self.assertTrue(r.poll_once())  # stable -> heartbeat this time
      self.assertEqual(post.call_args[0][0], "http://example.test/heartbeat")

  def test_failure_backs_off_exponentially(self):
    r = self._reporter()
    with mock.patch("openpilot.sunnypilot.carrot.cweb_push.get_local_ip", return_value="192.168.7.229"), \
         mock.patch("openpilot.sunnypilot.carrot.cweb_push.post_json", return_value=(False, 503, "down")) as post:
      r.poll_once()   # candidate frame
      self.assertFalse(r.poll_once())  # report attempt -> 503
      self.assertEqual(post.call_count, 1)
      self.assertAlmostEqual(r.backoff_s, 10.0)
      self.assertFalse(r.poll_once())  # within backoff window: no post
      r.next_retry_at = 0.0
      self.assertFalse(r.poll_once())
      self.assertAlmostEqual(r.backoff_s, 20.0)
      self.assertEqual(post.call_count, 2)

  def test_no_ip_resets_candidate(self):
    r = self._reporter()
    with mock.patch("openpilot.sunnypilot.carrot.cweb_push.get_local_ip", return_value=""):
      self.assertFalse(r.poll_once())
    self.assertTrue(r.was_down)
    self.assertEqual(r.current_candidate_ip, "")

  def test_payload_shape(self):
    # device_id() prefers the real DongleId when present; use a fresh empty
    # store so this exercises the hostname fallback on a provisioned device.
    params = mock.MagicMock()
    params.get.return_value = None
    with mock.patch("openpilot.sunnypilot.carrot.cweb_push.socket.gethostname", return_value="c3-dev"):
      self.assertEqual(device_id(params), "c3-dev")
    payload = build_payload(params, "192.168.7.229", 7000)
    self.assertEqual(payload, {"deviceId": mock.ANY, "ip": "192.168.7.229", "port": 7000})


if __name__ == "__main__":
  unittest.main()
