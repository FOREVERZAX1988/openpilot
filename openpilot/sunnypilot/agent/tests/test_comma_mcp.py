"""comma_mcp security-gate tests (PC-runnable, stdlib-only module).

Every gate here is fail-closed: the assertions below are the contract the
agent's tool layer promises the user - no write offroad, no key outside the
whitelist, no vehicle-control key ever, even if a whitelist edit goes wrong.
"""
import io
import json
import os
import tempfile
import unittest

from openpilot.sunnypilot.agent import comma_mcp


def _make_params_dir(tmp: str, values: dict[str, str] | None = None) -> str:
  params_dir = os.path.join(tmp, "params", "d")
  os.makedirs(params_dir, exist_ok=True)
  for key, value in (values or {}).items():
    with open(os.path.join(params_dir, key), "w", encoding="utf-8") as f:
      f.write(value)
  return params_dir


class TestControlBlacklist(unittest.TestCase):
  def test_tuning_families_refused(self):
    samples = [
      "LongitudinalTuning", "LateralTuning", "TurnLatControl", "LongitudinalPersonality",
      "Personality", "Mads", "MADS", "CustomAcc", "DynamicExperimentalControl",
      "AlphaLongitudinal", "CurvatureLateralCtrl",
    ]
    for key in samples:
      self.assertTrue(comma_mcp.is_control_param(key), key)

  def test_blacklist_beats_whitelist(self):
    # DisengageOnAccelerator sits on the writable whitelist deliberately, to
    # prove the blacklist wins. If this ever flips, the whitelist edit was the bug.
    self.assertIn("DisengageOnAccelerator", comma_mcp.WRITE_PARAM_WHITELIST)
    self.assertTrue(comma_mcp.is_control_param("DisengageOnAccelerator"))

  def test_whitelist_members_are_not_control_params(self):
    for key in comma_mcp.WRITE_PARAM_WHITELIST:
      if key == "DisengageOnAccelerator":
        continue
      self.assertFalse(comma_mcp.is_control_param(key), f"{key} must never look like a control param")


class TestOffroadGate(unittest.TestCase):
  def test_write_refused_without_explicit_offroad(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp)  # no IsOffroad file at all
      result = comma_mcp.tool_set_params({"params": {"ShowDebugInfo": True}}, params_dir)
      self.assertTrue(result.startswith("error:"), result)
      self.assertFalse(os.path.exists(os.path.join(params_dir, "ShowDebugInfo")))

  def test_write_refused_onroad(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"IsOffroad": "0"})
      result = comma_mcp.tool_set_params({"params": {"ShowDebugInfo": True}}, params_dir)
      self.assertTrue(result.startswith("error:"), result)
      self.assertIn("onroad", result)

  def test_write_allowed_offroad(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"IsOffroad": "1"})
      result = comma_mcp.tool_set_params({"params": {"ShowDebugInfo": True}}, params_dir)
      self.assertIn("written", result)
      with open(os.path.join(params_dir, "ShowDebugInfo"), encoding="utf-8") as f:
        self.assertEqual(f.read(), "1")

  def test_string_bool_values_coerced(self):
    # All whitelisted params are BOOL: the string "true" must become "1",
    # not be written verbatim (libparams would then read it as False).
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"IsOffroad": "1"})
      result = comma_mcp.tool_set_params({"params": {"ShowDebugInfo": "true", "IsMetric": "false"}}, params_dir)
      self.assertEqual(result.count("written"), 2)
      with open(os.path.join(params_dir, "ShowDebugInfo"), encoding="utf-8") as f:
        self.assertEqual(f.read(), "1")
      with open(os.path.join(params_dir, "IsMetric"), encoding="utf-8") as f:
        self.assertEqual(f.read(), "0")

  def test_non_bool_value_refused(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"IsOffroad": "1"})
      result = comma_mcp.tool_set_params({"params": {"ShowDebugInfo": "banana"}}, params_dir)
      self.assertIn("REFUSED", result)
      self.assertFalse(os.path.exists(os.path.join(params_dir, "ShowDebugInfo")))

  def test_reboot_refused_onroad(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"IsOffroad": "0"})
      self.assertTrue(comma_mcp.tool_reboot_device({}, params_dir).startswith("error:"))
      self.assertFalse(os.path.exists(os.path.join(params_dir, "DoReboot")))


class TestWhitelist(unittest.TestCase):
  def test_get_params_rejects_unknown_keys(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"DongleId": "deadbeef"})
      result = comma_mcp.tool_get_params({"keys": ["DongleId", "SecOCKey", "RandomKey"]}, params_dir)
      self.assertIn("DongleId = deadbeef", result)
      self.assertIn("SecOCKey = <not whitelisted>", result)
      self.assertIn("RandomKey = <not whitelisted>", result)

  def test_set_params_rejects_non_whitelisted_key(self):
    with tempfile.TemporaryDirectory() as tmp:
      params_dir = _make_params_dir(tmp, {"IsOffroad": "1"})
      result = comma_mcp.tool_set_params({"params": {"SshEnabled": True}}, params_dir)
      self.assertIn("not on the writable whitelist", result)
      self.assertFalse(os.path.exists(os.path.join(params_dir, "SshEnabled")))


class TestMcpProtocol(unittest.TestCase):
  def _serve(self, requests: list[dict], params_dir: str) -> list[dict]:
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    comma_mcp.serve(stdin=stdin, stdout=stdout, params_dir=params_dir)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]

  def test_initialize_and_tools_list(self):
    with tempfile.TemporaryDirectory() as tmp:
      responses = self._serve(
        [
          {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
          {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        _make_params_dir(tmp),
      )
      self.assertEqual(responses[0]["result"]["protocolVersion"], comma_mcp.PROTOCOL_VERSION)
      names = {tool["name"] for tool in responses[1]["result"]["tools"]}
      self.assertEqual(names, set(comma_mcp.TOOL_HANDLERS))
      self.assertNotIn("bash", names)  # shell execution is never offered

  def test_tools_call_offroad_error_shape(self):
    with tempfile.TemporaryDirectory() as tmp:
      responses = self._serve(
        [{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "set_params", "arguments": {"params": {"ShowDebugInfo": True}}}}],
        _make_params_dir(tmp),
      )
      result = responses[0]["result"]
      self.assertTrue(result["isError"])
      self.assertIn("onroad", result["content"][0]["text"])

  def test_unknown_tool_is_protocol_error(self):
    with tempfile.TemporaryDirectory() as tmp:
      responses = self._serve(
        [{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}}],
        _make_params_dir(tmp),
      )
      self.assertEqual(responses[0]["error"]["code"], -32602)


if __name__ == "__main__":
  unittest.main()
