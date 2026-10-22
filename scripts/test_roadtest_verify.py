#!/usr/bin/env python3
"""roadtest_verify.py 的判据单测 —— 全离车，纯函数，不需要 Params/vasm。

判据本身写错比不写更糟，所以这层必须有测试：门控的四个失败形状、反压地板、
开关值规整、以及 VAPID 私钥不能被回显。
"""
import unittest

from scripts.roadtest_verify import (
  SWITCHES,
  PARAMS_KEYS,
  check_writable,
  evaluate_status,
  keys_missing_from_so,
  normalize_value,
  parse_key_defaults,
  redact,
  verdict,
)

HEADER_SAMPLE = """
    {"CustomKp", {PERSISTENT | BACKUP, FLOAT, "1.0"}},
    {"VehicleTunesEnabled", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"LeadStopDepartPolicyEnabled", {PERSISTENT | BACKUP, BOOL, "0"}},  // comment, with comma
    {"WebPushVapid", {PERSISTENT | BACKUP, JSON}},
    {"LegacyNoDefault", {CLEAR_ON_MANAGER_START}},
"""


def good_status():
  return {
    "gate": {"active": True, "side": "left", "reason": "", "laneWidth": 3.4},
    "lane": {
      "cameraAvailable": True,
      "cameraError": None,
      "intervalSeconds": 0.6,
      "resultFresh": True,
      "lastFrameAgeSeconds": 0.1,
      "inference": {"latencyMs": 120.0},
    },
  }


def offroad_status():
  return {
    "gate": {"active": False, "side": "", "reason": "waiting for carState and modelV2", "laneWidth": 0.0},
    "lane": {"cameraAvailable": False, "intervalSeconds": 0.4, "resultFresh": False,
             "inference": {"latencyMs": 0.0}},
  }


class ParseKeyDefaultsTest(unittest.TestCase):
  def test_reads_bool_float_json_and_missing_default(self):
    d = parse_key_defaults(HEADER_SAMPLE)
    self.assertEqual(d["CustomKp"], "1.0")
    self.assertEqual(d["VehicleTunesEnabled"], "0")
    self.assertEqual(d["LeadStopDepartPolicyEnabled"], "0")
    self.assertIsNone(d["WebPushVapid"])          # JSON 类型没有默认值
    self.assertIsNone(d["LegacyNoDefault"])

  def test_ignores_trailing_comment_and_commas(self):
    self.assertEqual(len(parse_key_defaults(HEADER_SAMPLE)), 5)

  def test_every_switch_is_registered_in_the_real_header(self):
    if not PARAMS_KEYS.exists():
      self.skipTest("params_keys.h not present in this checkout")
    registered = parse_key_defaults(PARAMS_KEYS.read_text(encoding="utf-8"))
    missing = [k for k in SWITCHES if k not in registered]
    self.assertEqual(missing, [], f"switch keys missing from params_keys.h: {missing}")

  def test_switch_defaults_match_the_header(self):
    if not PARAMS_KEYS.exists():
      self.skipTest("params_keys.h not present in this checkout")
    registered = parse_key_defaults(PARAMS_KEYS.read_text(encoding="utf-8"))
    for key, (expected, _owner, _why) in SWITCHES.items():
      if expected is None:
        continue
      self.assertEqual(registered[key], expected, f"{key} default drifted from the docstring/UI")


class SoKeyCheckTest(unittest.TestCase):
  def test_reports_only_keys_the_library_does_not_know(self):
    so = b"\x00CustomKp\x00VehicleTunesEnabled\x00other_string\x00"
    self.assertEqual(keys_missing_from_so(so, ["CustomKp", "LeadStopDepartPolicyEnabled"]),
                     ["LeadStopDepartPolicyEnabled"])

  def test_empty_library_reports_everything(self):
    self.assertEqual(sorted(keys_missing_from_so(b"", ["CustomKp", "WebPushVapid"])),
                     ["CustomKp", "WebPushVapid"])


class WritableGuardTest(unittest.TestCase):
  def test_refuses_while_onroad(self):
    ok, why = check_writable(False)
    self.assertFalse(ok)
    self.assertIn("onroad", why)

  def test_allows_offroad(self):
    ok, why = check_writable(True)
    self.assertTrue(ok)
    self.assertIn("offroad", why)


class EvaluateStatusTest(unittest.TestCase):
  def test_good_onroad_payload_passes(self):
    checks = evaluate_status(good_status())
    self.assertTrue(verdict(checks), [c for c in checks if not c["info"] and not c["ok"]])

  def test_offroad_payload_fails_on_camera_lane_width_and_reason(self):
    checks = evaluate_status(offroad_status())
    failing = {c["check"] for c in checks if not c["info"] and not c["ok"]}
    self.assertFalse(verdict(checks))
    for expected in ("lane.cameraAvailable", "gate.laneWidth > 0", "gate.reason != waiting",
                     "lane.intervalSeconds >= 0.6"):
      self.assertIn(expected, failing)

  def test_info_checks_do_not_decide_the_verdict(self):
    status = good_status()
    status["lane"]["resultFresh"] = False          # 无车道时合法，只作参考
    status["gate"]["laneWidth"] = 2.0              # 低于 3.0 m 门限也合法
    checks = evaluate_status(status)
    self.assertTrue(verdict(checks))
    self.assertTrue(any(c["info"] for c in checks))

  def test_backpressure_floor_is_latency_times_1_15(self):
    status = good_status()
    status["lane"]["intervalSeconds"] = 0.6        # 120ms * 1.15 = 0.138 -> 0.6 够
    self.assertTrue(verdict(evaluate_status(status)))
    status["lane"]["inference"]["latencyMs"] = 600.0   # 600 * 1.15 = 0.69 > 0.6
    checks = evaluate_status(status)
    self.assertFalse(verdict(checks))
    self.assertTrue(any(c["check"] == "interval >= latency*1.15" and not c["ok"] for c in checks))

  def test_missing_inference_block_does_not_crash(self):
    checks = evaluate_status({"gate": {}, "lane": {}})
    self.assertFalse(verdict(checks))
    self.assertTrue(all("check" in c for c in checks))


class NormalizeValueTest(unittest.TestCase):
  def test_bool_spellings(self):
    for raw in ("1", "true", "ON", " yes "):
      self.assertEqual(normalize_value("LeadFollowPolicyEnabled", raw), "1")
    for raw in ("0", "false", "Off", "no"):
      self.assertEqual(normalize_value("LeadFollowPolicyEnabled", raw), "0")

  def test_bool_rejects_garbage(self):
    with self.assertRaises(ValueError):
      normalize_value("VehicleTunesEnabled", "maybe")

  def test_custom_kp_formats_two_decimals(self):
    self.assertEqual(normalize_value("CustomKp", "1.05"), "1.05")
    self.assertEqual(normalize_value("CustomKp", "1.1"), "1.10")

  def test_custom_kp_range_is_enforced(self):
    for raw in ("0.4", "2.5"):
      with self.assertRaises(ValueError):
        normalize_value("CustomKp", raw)


class RedactionTest(unittest.TestCase):
  def test_vapid_private_key_never_echoed(self):
    secret = {"private_key": "MIGHAgEAMBMGByqGSM49", "public_key": "BL6I2ebT"}
    out = redact("WebPushVapid", secret)
    self.assertEqual(out, {"public_key": "<set>", "private_key": "<redacted>"})
    self.assertNotIn("MIGHAgEAMBMGByqGSM49", str(out))

  def test_subscriptions_reduce_to_a_count(self):
    self.assertEqual(redact("WebPushSubscriptions", [{"endpoint": "https://x"}, {"endpoint": "https://y"}]),
                     "<2 subscription(s)>")

  def test_normal_keys_pass_through(self):
    self.assertEqual(redact("CustomKp", "1.00"), "1.00")


if __name__ == "__main__":
  unittest.main()
