"""tailscale.py state-protocol + opencode_config generation tests (PC-runnable)."""
import unittest

from openpilot.sunnypilot.agent.tailscale import parse_tailscale_state
from openpilot.sunnypilot.agent.opencode_config import build_opencode_config, generate_password


class TestTailscaleState(unittest.TestCase):
  def test_empty(self):
    self.assertEqual(parse_tailscale_state(None).status, "")
    self.assertEqual(parse_tailscale_state("").status, "")
    self.assertEqual(parse_tailscale_state("   ").status, "")

  def test_pairing(self):
    state = parse_tailscale_state("pairing|https://login.tailscale.com/a/abc123")
    self.assertEqual(state.status, "pairing")
    self.assertEqual(state.url, "https://login.tailscale.com/a/abc123")

  def test_joined(self):
    state = parse_tailscale_state("joined|comma-abcd.|100.64.0.5")
    self.assertEqual(state.status, "joined")
    self.assertEqual(state.name, "comma-abcd.")
    self.assertEqual(state.ip, "100.64.0.5")

  def test_error_keeps_full_message(self):
    state = parse_tailscale_state("error|tailscale up failed: exit 1|retry")
    self.assertEqual(state.status, "error")
    self.assertEqual(state.message, "tailscale up failed: exit 1|retry")

  def test_unknown_payload_is_preserved(self):
    state = parse_tailscale_state("weird|stuff")
    self.assertEqual(state.status, "weird")
    self.assertEqual(state.message, "weird|stuff")


class TestOpencodeConfig(unittest.TestCase):
  def test_permissions_denied_by_default(self):
    config = build_opencode_config("", "", "", ["wrapper.sh"])
    self.assertEqual(config["permission"]["bash"], {"*": "deny"})
    self.assertEqual(config["permission"]["edit"], "ask")
    self.assertEqual(config["permission"]["webfetch"], "deny")

  def test_mcp_server_registered(self):
    config = build_opencode_config("", "", "", ["/data/agent_ws/comma_mcp_launch.sh"])
    server = config["mcp"]["comma-tools"]
    self.assertEqual(server["type"], "local")
    self.assertTrue(server["enabled"])
    self.assertEqual(server["command"], ["/data/agent_ws/comma_mcp_launch.sh"])

  def test_provider_only_with_base_and_model(self):
    config = build_opencode_config("", "deepseek-chat", "sk-x", ["w.sh"])
    self.assertNotIn("provider", config)
    self.assertNotIn("model", config)

    config = build_opencode_config("http://192.168.2.10:8000/v1", "deepseek-chat", "", ["w.sh"])
    self.assertEqual(config["model"], "selfhosted/deepseek-chat")
    options = config["provider"]["selfhosted"]["options"]
    self.assertEqual(options["baseURL"], "http://192.168.2.10:8000/v1")
    self.assertNotIn("apiKey", options)

  def test_api_key_injected_when_present(self):
    config = build_opencode_config("http://x/v1", "m", "sk-secret", ["w.sh"])
    self.assertEqual(config["provider"]["selfhosted"]["options"]["apiKey"], "sk-secret")

  def test_password_strength(self):
    self.assertGreaterEqual(len(generate_password()), 16)
    self.assertNotEqual(generate_password(), generate_password())


if __name__ == "__main__":
  unittest.main()
