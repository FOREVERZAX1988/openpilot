"""Manager-hosted launcher for the built-in AI agent (opencode web, port 5095).

Registered in system/manager/process_config.py behind the ai_agent_run gate:
offroad only, gated on AgentEnabled, and stopped whenever AgentSuspended is set
(the idle watchdog below writes that flag before a clean exit so the manager
does not immediately respawn an idle process).
Responsibilities:
- ensure AgentPassword exists (generated once, shown in the UI + web panel)
- generate the opencode config via sunnypilot/agent/opencode_config.py into the
  agent workspace, both via OPENCODE_CONFIG and the XDG path so the launcher
  works across opencode config-discovery changes
- spawn `opencode web --hostname 0.0.0.0 --port 5095` with the password env
- idle watchdog: with no browser connected to 5095 for IDLE_EXIT_MINUTES the
  process writes AgentSuspended and exits (parked devices keep the RAM)

Config schema is pinned to opencode v2.3.0 (see agnos-builder
userspace/agent_setup.sh); validate against the locked binary when bumping
either side.
"""
import json
import os
import shutil
import subprocess
import time

from openpilot.common.params import Params
from openpilot.common.realtime import set_core_affinity
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.agent.opencode_config import build_opencode_config, generate_password

AGENT_PORT = 5095
AGENT_WS = "/data/agent_ws"
# Model-provider API key store. The key lives in a 0600 file, not a param:
# params are world-readable on device and ride along in param backups.
AGENT_ENV_DIR = "/data/agent"
API_KEY_PATH = "/data/agent/env"
OPENCODE_BIN = "/usr/local/bin/opencode"
IDLE_EXIT_MINUTES = 30
IDLE_CHECK_SECONDS = 60.0


def ensure_password(params: Params) -> str:
  password = params.get("AgentPassword")
  if password:
    return password
  password = generate_password()
  params.put("AgentPassword", password, block=True)
  return password


def reset_password(params: Params) -> str:
  """Regenerate the web login password.

  The running agent keeps the old password in its environment until it exits;
  main() below watches the param and restarts the process within one idle
  poll, so a reset becomes effective without a device reboot.
  """
  password = generate_password()
  params.put("AgentPassword", password, block=True)
  params.remove("AgentSuspended")
  return password


def ensure_api_key(params: Params) -> str:
  """Move the AgentApiKey dropbox param into the 0600 key file, then read it.

  AgentApiKey is a one-way channel: the user writes the param (via SSH or a
  future UI), the next agent start relocates the value to
  /data/agent/env (0600) and removes the param, so the key no longer shows
  up in param backups or generic param reads. To rotate: write the param
  again, or edit the file directly over SSH.
  """
  key = params.get("AgentApiKey")
  if key:
    os.makedirs(AGENT_ENV_DIR, exist_ok=True)
    tmp = API_KEY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
      f.write(key)
    os.chmod(tmp, 0o600)
    os.replace(tmp, API_KEY_PATH)
    params.remove("AgentApiKey")
    cloudlog.info("moved AgentApiKey param into %s (0600) and cleared the param", API_KEY_PATH)
  try:
    with open(API_KEY_PATH, encoding="utf-8") as f:
      return f.read().strip()
  except OSError:
    return ""


def _established_connections(port: int) -> int:
  """ESTABLISHED TCP connections to the agent port, from /proc (no netstat dep)."""
  count = 0
  hex_port = f"{port:04X}"
  for kind in ("tcp", "tcp6"):
    try:
      with open(f"/proc/net/{kind}", encoding="utf-8") as f:
        lines = f.read().splitlines()[1:]
    except OSError:
      continue
    for line in lines:
      parts = line.split()
      # local_address (col 1) and state (col 3); 01 = ESTABLISHED
      if len(parts) >= 4 and parts[1].rsplit(":", 1)[-1] == hex_port and parts[3] == "01":
        count += 1
  return count


def write_mcp_wrapper(path: str) -> str:
  """Standalone launcher so opencode can spawn comma_mcp without openpilot's env.

  comma_mcp is stdlib-only and reads params as files, so it only needs the repo
  on PYTHONPATH (same layout the device launcher uses).
  """
  script = "\n".join([
    "#!/usr/bin/env bash",
    "export PYTHONPATH=\"/data/openpilot${PYTHONPATH:+:$PYTHONPATH}\"",
    "exec /usr/bin/python3 -m openpilot.sunnypilot.agent.comma_mcp",
    "",
  ])
  with open(path, "w", encoding="utf-8") as f:
    f.write(script)
  os.chmod(path, 0o755)
  return path


def main() -> None:
  params = Params()

  # Parked-device hygiene: the manager gate already excludes onroad/PC; the
  # suspend marker lets the idle watchdog below stop respawning.
  if params.get_bool("AgentSuspended"):
    return

  password = ensure_password(params)
  api_key = ensure_api_key(params)
  os.makedirs(AGENT_WS, exist_ok=True)

  wrapper = write_mcp_wrapper(os.path.join(AGENT_WS, "comma_mcp_launch.sh"))
  config = build_opencode_config(
    base_url=params.get("AgentModelBase") or "",
    model_id=params.get("AgentModelId") or "",
    api_key=api_key,
    mcp_command=[wrapper],
  )
  config_json = json.dumps(config, indent=2) + "\n"

  config_env_path = os.path.join(AGENT_WS, "opencode.json")
  with open(config_env_path, "w", encoding="utf-8") as f:
    f.write(config_json)

  # Second copy under XDG discovery for opencode builds that ignore OPENCODE_CONFIG.
  xdg_dir = os.path.join(AGENT_WS, ".config", "opencode")
  os.makedirs(xdg_dir, exist_ok=True)
  with open(os.path.join(xdg_dir, "opencode.json"), "w", encoding="utf-8") as f:
    f.write(config_json)

  env = os.environ.copy()
  env["OPENCODE_SERVER_PASSWORD"] = password
  env["OPENCODE_CONFIG"] = config_env_path
  env["XDG_CONFIG_HOME"] = os.path.join(AGENT_WS, ".config")

  binary = OPENCODE_BIN if os.path.exists(OPENCODE_BIN) else shutil.which("opencode")
  if binary is None:
    cloudlog.error("opencode binary not found - AgentEnabled is set but userspace/agent_setup.sh did not run on this image")
    # Suspend instead of returning "cleanly": with the gate still true the
    # manager would otherwise respawn this process every cycle and spam the
    # log. The toggle (UI or web panel) clears the marker on re-enable.
    params.put_bool("AgentSuspended", True, block=True)
    return

  # Parked diagnostics only: keep off the realtime cores, mirroring carrot_server.
  try:
    set_core_affinity([0, 1, 2, 3])
  except Exception:
    cloudlog.exception("failed to set agent core affinity")

  cmd = [binary, "web", "--hostname", "0.0.0.0", "--port", str(AGENT_PORT)]
  cloudlog.info(f"starting AI agent: {' '.join(cmd)}")
  proc = subprocess.Popen(cmd, cwd=AGENT_WS, env=env)

  idle_deadline = time.monotonic() + IDLE_EXIT_MINUTES * 60
  try:
    while proc.poll() is None:
      time.sleep(IDLE_CHECK_SECONDS)
      # A password reset (UI or web panel) regenerates the param; restart so
      # the new password is in the server env. The manager respawns us.
      if params.get("AgentPassword") != password:
        cloudlog.info("AI agent password changed, restarting to apply it")
        break
      if _established_connections(AGENT_PORT) > 0:
        idle_deadline = time.monotonic() + IDLE_EXIT_MINUTES * 60
      elif time.monotonic() >= idle_deadline:
        cloudlog.info(f"AI agent idle for {IDLE_EXIT_MINUTES}min, suspending")
        params.put_bool("AgentSuspended", True, block=True)
        proc.terminate()
        break
  finally:
    if proc.poll() is None:
      proc.terminate()
      try:
        proc.wait(timeout=10)
      except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
  main()
