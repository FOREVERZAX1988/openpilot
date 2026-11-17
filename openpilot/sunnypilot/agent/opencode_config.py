"""opencode.json generation - pure stdlib, no openpilot imports, PC-testable.

Schema is pinned to opencode v2.3.0 (see agnos-builder userspace/agent_setup.sh);
validate against the locked binary whenever either side is bumped.

The permission block is the second security layer of the agent (comma_mcp.py's
offroad/whitelist/blacklist gates are the first and third): builtin opencode
tools are restricted by tier and device control goes exclusively through the
comma-tools MCP server.

Permission tiers (AgentWorkshopMode param, STRING):
- "" (default): read-only diagnosis station - edit/bash/shell/web/subagent/skill
  all denied, device control only via MCP tools.
- "edit": workshop edit mode - builtin edits within the project fence, web
  lookups, subagents and skills are allowed; shell stays on "ask" so every
  command needs an explicit approval click in the web UI (opencode v2 schema
  defines the "ask" effect).
- "full": full workshop - shell allowed outright. Root shell on the car
  computer; the user accepts reflash risk and sets this explicitly over SSH.
The agent CANNOT change its own tier: AgentWorkshopMode is deliberately not on
comma_mcp's write whitelist and /data/params is fenced off from builtin tools.
"""
import secrets

OPENCODE_CONFIG_VERSION = "v2.3.0"

# opencode v2 permission actions for the builtin terminal tool. The schema's
# deprecated map format keys it "bash"; the ruleset format matches free-form
# action strings. Deny/ask BOTH names so a naming drift in either direction
# cannot silently open a shell.
SHELL_ACTIONS = ("bash", "shell")
# Likewise for subagents: newer builds register "subagent", older ones "task".
SUBAGENT_ACTIONS = ("subagent", "task")

COMMA_AGENT_PROMPT = (
  "You are comma-agent, the on-device assistant of a comma-style openpilot unit. "
  + "The user is the car's owner, talking to you from a browser. "
  + "Your project is the running openpilot source tree at /data/openpilot: you may "
  + "read and search its code to ground diagnoses in the real implementation "
  + "(cite file paths). "
  + "Diagnose issues from real log output (use read_logs/dmesg, quote what you see), "
  + "report hardware state with system_stats, and only change device settings through "
  + "set_params after explaining what you will do - every write needs the user's explicit approval. "
  + "Never guess about vehicle behaviour: describe only what the tools return. "
  + "Driving-safety parameters are hard-blocked and not negotiable."
)

PROMPT_SUFFIX = {
  "": "This is a read-only diagnosis station: you cannot edit code or run shell commands.",
  "edit": (
    "Workshop edit mode: you may edit files INSIDE /data/openpilot only (anything "
    + "outside is fenced off), use web lookups, subagents and skills. Shell commands "
    + "require the user's explicit approval every time - batch what you need into "
    + "few, clearly explained commands."
  ),
  "full": (
    "Full workshop mode: you may edit files inside /data/openpilot and run shell "
    + "commands. The shell runs as root on the car's computer - treat it with the "
    + "same care as production infrastructure: no destructive commands without "
    + "explaining them first, never touch /data/params or key material, and never "
    + "modify vehicle-control parameters or opendbc safety logic."
  ),
}

# Valid tiers; anything else falls back to the read-only default.
WORKSHOP_MODES = ("", "edit", "full")


def generate_password() -> str:
  return secrets.token_urlsafe(12)


def _shell_rules(effect: str) -> list[dict]:
  return [{"action": action, "resource": "*", "effect": effect} for action in SHELL_ACTIONS]


def _subagent_rules(effect: str) -> list[dict]:
  return [{"action": action, "resource": "*", "effect": effect} for action in SUBAGENT_ACTIONS]


def build_permissions(workshop_mode: str) -> list[dict]:
  """Tiered permission ruleset. Last matching rule wins; base policy is allow-all,
  so every action that must be off has an explicit final rule.

  ""  -> read-only diagnosis station
  edit -> edits inside the fence, web, subagents, skills; shell asks
  full -> everything including shell
  """
  mode = workshop_mode if workshop_mode in WORKSHOP_MODES else ""
  rules: list[dict] = [
    # External paths (anything outside the project location) first-line deny.
    # This fence holds in every tier: even with edit/bash allowed, builtin
    # tools never reach /data/params, /data/agent or key material.
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
    # The web UI renders approval prompts; keep the question channel open.
    {"action": "question", "resource": "*", "effect": "allow"},
  ]

  if mode in ("edit", "full"):
    # Mutating tools scoped by the external_directory fence above.
    rules.append({"action": "edit", "resource": "*", "effect": "allow"})
    rules.append({"action": "webfetch", "resource": "*", "effect": "allow"})
    rules.append({"action": "websearch", "resource": "*", "effect": "allow"})
    rules.extend(_subagent_rules("allow"))
    rules.append({"action": "skill", "resource": "*", "effect": "allow"})

  if mode == "edit":
    rules.extend(_shell_rules("ask"))
  elif mode == "full":
    rules.extend(_shell_rules("allow"))
  else:
    rules.extend(_shell_rules("deny"))
    rules.append({"action": "edit", "resource": "*", "effect": "deny"})
    rules.append({"action": "webfetch", "resource": "*", "effect": "deny"})
    rules.append({"action": "websearch", "resource": "*", "effect": "deny"})
    rules.extend(_subagent_rules("deny"))
    rules.append({"action": "skill", "resource": "*", "effect": "deny"})

  return rules


def build_opencode_config(base_url: str, model_id: str, api_key: str, mcp_command: list[str],
                          workshop_mode: str = "", instructions: list[str] | None = None) -> dict:
  mode = workshop_mode if workshop_mode in WORKSHOP_MODES else ""
  config: dict = {
    "$schema": "https://opencode.ai/config.json",
    "permissions": build_permissions(mode),
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
        "prompt": COMMA_AGENT_PROMPT + " " + PROMPT_SUFFIX[mode],
        "mode": "all",
      },
    },
  }

  # Ambient automotive-expert context (opencode v2 "instructions"; paths are
  # resolved by opencode relative to the config location). Empty entries are
  # filtered so a missing knowledge dir never breaks config generation.
  paths = [p for p in (instructions or []) if p and p.strip()]
  if paths:
    config["instructions"] = paths

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
