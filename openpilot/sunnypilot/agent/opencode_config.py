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
  + "Your project is the running openpilot source tree at /data/openpilot: you may "
  + "read and search its code to ground diagnoses in the real implementation "
  + "(cite file paths), but you cannot edit it. "
  + "Diagnose issues from real log output (use read_logs/dmesg, quote what you see), "
  + "report hardware state with system_stats, and only change device settings through "
  + "set_params after explaining what you will do - every write needs the user's explicit approval. "
  + "Never guess about vehicle behaviour: describe only what the tools return. "
  + "Driving-safety parameters are hard-blocked and not negotiable."
)


def generate_password() -> str:
  return secrets.token_urlsafe(12)


def build_opencode_config(base_url: str, model_id: str, api_key: str, mcp_command: list[str]) -> dict:
  # Device control goes exclusively through the comma-tools MCP server.
  #
  # Permission model (opencode v2 "permissions" array; last matching rule wins,
  # and every agent starts from an allow-all base policy, so deny rules must be
  # explicit). The agent's project is /data/openpilot: reads/greps inside the
  # source tree are allowed (code diagnosis), while every path outside the
  # project - /data/params, /data/agent, /data/media - is fenced off by
  # external_directory deny, so builtin tools can never reach the params store
  # or key material. Edit/shell/web/subagent stay hard-denied: a read-only
  # diagnosis station. MCP tools are unaffected by these actions.
  # Validate this rule list against the locked binary whenever opencode is
  # bumped - a NEW builtin action defaults to allow, not deny.
  config: dict = {
    "$schema": "https://opencode.ai/config.json",
    "permissions": [
      # External paths (anything outside the project location) first-line deny.
      {"action": "external_directory", "resource": "*", "effect": "deny"},
      # Project reads: allowed, except secrets-shaped files (belt-and-suspenders;
      # the device tree carries no .env, but future forks might).
      {"action": "read", "resource": "*", "effect": "allow"},
      {"action": "read", "resource": "*.env", "effect": "deny"},
      {"action": "read", "resource": "*.env.*", "effect": "deny"},
      {"action": "read", "resource": ".git/*", "effect": "deny"},
      {"action": "read", "resource": ".git", "effect": "deny"},
      # Project search/index without content writes.
      {"action": "grep", "resource": "*", "effect": "allow"},
      {"action": "glob", "resource": "*", "effect": "allow"},
      {"action": "list", "resource": "*", "effect": "allow"},
      # Everything mutating or leaving the box stays denied.
      {"action": "edit", "resource": "*", "effect": "deny"},
      {"action": "shell", "resource": "*", "effect": "deny"},
      {"action": "webfetch", "resource": "*", "effect": "deny"},
      {"action": "websearch", "resource": "*", "effect": "deny"},
      {"action": "subagent", "resource": "*", "effect": "deny"},
      {"action": "skill", "resource": "*", "effect": "deny"},
      # The web UI renders approval prompts; keep the question channel open.
      {"action": "question", "resource": "*", "effect": "allow"},
    ],
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
        "mode": "all",
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
