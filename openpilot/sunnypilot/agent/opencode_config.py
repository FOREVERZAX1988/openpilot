"""opencode.json generation - pure stdlib, no openpilot imports, PC-testable.

Schema is pinned to opencode v2.3.0 (see agnos-builder userspace/agent_setup.sh);
validate against the locked binary whenever either side is bumped.

The permission block is the second security layer of the agent (comma_mcp.py's
offroad/whitelist/blacklist gates are the first and third): every builtin
opencode tool is denied and device control goes exclusively through the
comma-tools MCP server.
"""
import secrets

OPENCODE_CONFIG_VERSION = "v2.3.0"

COMMA_AGENT_PROMPT = (
  "You are comma-agent, the on-device assistant of a comma-style openpilot unit. "
  + "The user is the car's owner, talking to you from a browser. "
  + "Diagnose issues from real log output (use read_logs/dmesg, quote what you see), "
  + "report hardware state with system_stats, and only change device settings through "
  + "set_params after explaining what you will do - every write needs the user's explicit approval. "
  + "Never guess about vehicle behaviour: describe only what the tools return. "
  + "Driving-safety parameters are hard-blocked and not negotiable."
)


def generate_password() -> str:
  return secrets.token_urlsafe(12)


def build_opencode_config(base_url: str, model_id: str, api_key: str, mcp_command: list[str]) -> dict:
  # Device control goes exclusively through the comma-tools MCP server: every
  # builtin tool that reads arbitrary files or reaches the network is denied
  # outright, because the agent runs as root and opencode's read/grep would
  # otherwise bypass comma_mcp's param whitelist entirely (AgentApiKey, params,
  # SSH material). edit/task/lsp are useless without read and equally denied.
  # Validate this key list against the locked binary's tool registry whenever
  # opencode is bumped - a NEW builtin defaults to allow, not deny.
  config: dict = {
    "$schema": "https://opencode.ai/config.json",
    "permission": {
      "bash": {"*": "deny"},
      "webfetch": "deny",
      "websearch": "deny",
      "read": "deny",
      "grep": "deny",
      "glob": "deny",
      "list": "deny",
      "edit": "deny",
      "task": "deny",
      "lsp": "deny",
      "codesearch": "deny",
    },
    "mcp": {
      "comma-tools": {
        "type": "local",
        "command": mcp_command,
        "enabled": True,
      },
    },
    "agent": {
      "comma-agent": {
        "description": "On-device comma unit assistant",
        "prompt": COMMA_AGENT_PROMPT,
      },
    },
  }

  if base_url and model_id:
    provider_id = "selfhosted"
    provider_options: dict = {"baseURL": base_url}
    if api_key:
      provider_options["apiKey"] = api_key
    config["provider"] = {
      provider_id: {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Self-hosted",
        "options": provider_options,
        "models": {model_id: {"name": model_id}},
      },
    }
    config["model"] = f"{provider_id}/{model_id}"
  return config
