"""Minimal MCP stdio server exposing a whitelisted tool set to the AI agent.

Protocol: JSON-RPC 2.0 over stdio per the MCP spec (initialize / ping /
tools/list / tools/call). Deliberately dependency-free (stdlib only): opencode
spawns this process itself, so it must not depend on openpilot's import
environment. Params are read as raw files from /data/params/d, the same
mechanism AGNOS's ssh-param-watcher uses.

Security model - three independent gates, all fail-closed:

1. Offroad hard gate: every write tool re-checks Params IsOffroad at call time.
   The manager only stops the agent process on the offroad transition; between
   that transition and process teardown there is a window that this gate
   narrows to milliseconds (re-checked per key) without eliminating it.
   Anything but an explicit True is treated as onroad/unknown.
2. Whitelist: only listed param keys are readable/writable at all. get_params
   and set_params reject everything else.
3. Control blacklist: vehicle-control-related keys are refused even if a later
   edit puts them on a whitelist. Test-locked in tests/test_comma_mcp.py.

Shell execution is NOT offered as a tool. opencode's own permissions config
(agent_process.py) additionally denies its builtin bash tool.
"""
import json
import os
import re
import shutil
import subprocess
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "comma-tools"
SERVER_VERSION = "1.0.0"

# Write tools are allowed only while the car is explicitly parked.
OFFROAD_PARAM = "IsOffroad"

# Params the agent may READ (device diagnostics / identity). Keep this boring.
READ_PARAM_WHITELIST = frozenset({
  "DongleId",
  "GitBranch",
  "GitCommit",
  "UpdaterState",
  "UpdateAvailable",
  "IsOffroad",
  "NetworkAddress",
  "LastOffroadStatusPacket",
})

# Params the agent may WRITE after explicit user approval. Everything that
# influences the control chain is absent by construction; the blacklist below
# is the second line of defense if this set is ever edited carelessly.
WRITE_PARAM_WHITELIST = frozenset({
  "ShowDebugInfo",
  "IsMetric",
  "RecordAudio",
  "RecordFront",
  "IsLdwEnabled",
  "DisengageOnAccelerator",
  "HotspotOnBoot",
})

# Refused unconditionally, even if someone later adds them to a whitelist.
# Prefixes cover tuning families; exact names cover single keys.
CONTROL_PARAM_BLACKLIST_PREFIXES = (
  "LongitudinalTuning",
  "LateralTuning",
  "TurnLatControl",
  "LongitudinalPersonality",
  "Personality",
  "Mads",
  "MADS",
  "CustomAcc",
  "DynamicExperimentalControl",
  "AlphaLongitudinal",
  "CurvatureLateralCtrl",
)
CONTROL_PARAM_BLACKLIST_EXACT = frozenset({
  "ExperimentalMode",
  "ExperimentalModeConfirmed",
  "OpenpilotEnabledToggle",
  "DisengageOnAccelerator",  # driver-facing but control-adjacent: read-only for the agent
})

MAX_LINES = 400
ROUTE_DIR = "/data/media/0/realdata"

# Mirrors system/loggerd/uploader.py UPLOAD_ATTR_NAME/VALUE (stdlib-only here,
# so the constant is duplicated; the uploader owns the semantics).
UPLOAD_XATTR_NAME = "user.upload"
UPLOAD_XATTR_VALUE = b"1"

# Route names the agent may ask the uploader to prioritise. Real route dirs
# look like "2026-11-16--10-30-00"; rejecting everything else keeps commas,
# pipes and newlines out of the AthenadRecentlyViewedRoutes CSV param.
ROUTE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_ROUTE_ENTRIES = 10


def is_control_param(key: str) -> bool:
  if key in CONTROL_PARAM_BLACKLIST_EXACT:
    return True
  return any(key.startswith(prefix) for prefix in CONTROL_PARAM_BLACKLIST_PREFIXES)


def is_offroad(params_dir: str) -> bool:
  """Fail-closed: writes are allowed ONLY on an explicit IsOffroad=True."""
  try:
    with open(os.path.join(params_dir, OFFROAD_PARAM), encoding="utf-8") as f:
      return f.read().strip() == "1"
  except OSError:
    return False


def read_param_file(params_dir: str, key: str) -> str | None:
  try:
    with open(os.path.join(params_dir, key), encoding="utf-8") as f:
      return f.read().strip()
  except OSError:
    return None


def coerce_bool_value(value) -> str | None:
  """Normalize an incoming bool-ish value to a params BOOL literal.

  Every key on WRITE_PARAM_WHITELIST is a BOOL param; writing the string
  "true" would libparams-read as False, so anything that is not a clean
  bool representation is refused instead of written.
  """
  if value is True:
    return "1"
  if value is False:
    return "0"
  if isinstance(value, str):
    lowered = value.strip().lower()
    if lowered in ("1", "true"):
      return "1"
    if lowered in ("0", "false"):
      return "0"
  if isinstance(value, int) and value in (0, 1):
    return str(value)
  return None


def write_param_file(params_dir: str, key: str, value: str) -> None:
  tmp = os.path.join(params_dir, key + ".tmp")
  with open(tmp, "w", encoding="utf-8") as f:
    f.write(value)
  os.replace(tmp, os.path.join(params_dir, key))


# ── tool implementations ─────────────────────────────────────────────────────

def tool_read_logs(arguments: dict, params_dir: str) -> str:
  lines = min(int(arguments.get("lines") or 100), MAX_LINES)
  proc = subprocess.run(
    ["journalctl", "-n", str(lines), "--no-pager"],
    check=False, capture_output=True, encoding="utf-8", errors="replace", timeout=10,
  )
  return proc.stdout[-50000:] or proc.stderr or "no journal output"


def tool_dmesg(arguments: dict, params_dir: str) -> str:
  lines = min(int(arguments.get("lines") or 100), MAX_LINES)
  proc = subprocess.run(
    ["dmesg"], check=False, capture_output=True, encoding="utf-8", errors="replace", timeout=10,
  )
  return "\n".join(proc.stdout.splitlines()[-lines:])[-50000:] or proc.stderr or "no dmesg output"


def tool_system_stats(arguments: dict, params_dir: str) -> str:
  try:
    meminfo = {}
    with open("/proc/meminfo", encoding="utf-8") as f:
      for line in f:
        key, _, value = line.partition(":")
        meminfo[key.strip()] = value.strip()
    mem_total = int(meminfo.get("MemTotal", "0 kB").split()[0]) // 1024
    mem_available = int(meminfo.get("MemAvailable", "0 kB").split()[0]) // 1024
  except (OSError, ValueError, IndexError):
    mem_total = mem_available = -1

  try:
    with open("/proc/loadavg", encoding="utf-8") as f:
      load = f.read().split()[:3]
  except OSError:
    load = []

  temps = []
  try:
    for zone in sorted(os.listdir("/sys/devices/virtual/thermal")):
      if not zone.startswith("thermal_zone"):
        continue
      try:
        with open(f"/sys/devices/virtual/thermal/{zone}/type", encoding="utf-8") as f:
          ztype = f.read().strip()
        with open(f"/sys/devices/virtual/thermal/{zone}/temp", encoding="utf-8") as f:
          ztemp = int(f.read().strip()) / 1000.0
        temps.append(f"{ztype}: {ztemp:.1f}C")
      except (OSError, ValueError):
        continue
  except OSError:
    pass

  disk = shutil.disk_usage("/")
  offroad = is_offroad(params_dir)
  return "\n".join([
    f"memory: {mem_available}MiB available / {mem_total}MiB total",
    f"load: {' '.join(load)}",
    f"disk /: {disk.free // (1 << 30)}GiB free / {disk.total // (1 << 30)}GiB",
    f"temperatures: {'; '.join(temps) or 'unavailable'}",
    f"offroad: {offroad}",
  ])


def tool_list_routes(arguments: dict, params_dir: str) -> str:
  count = min(int(arguments.get("count") or 20), 100)
  try:
    routes = sorted(os.listdir(ROUTE_DIR), reverse=True)[:count]
    return "\n".join(routes) if routes else "no routes recorded"
  except OSError as exc:
    return f"cannot list routes: {exc}"


def tool_get_params(arguments: dict, params_dir: str) -> str:
  keys = arguments.get("keys") or []
  if not isinstance(keys, list):
    return "error: keys must be a list"
  out = {}
  for key in keys:
    key = str(key)
    if key not in READ_PARAM_WHITELIST:
      out[key] = "<not whitelisted>"
      continue
    value = read_param_file(params_dir, key)
    out[key] = value if value is not None else "<unset>"
  return "\n".join(f"{key} = {value}" for key, value in out.items())


def tool_set_params(arguments: dict, params_dir: str) -> str:
  if not is_offroad(params_dir):
    return "error: vehicle is onroad (or state unknown) - only read-only queries are allowed while driving"

  updates = arguments.get("params") or {}
  if not isinstance(updates, dict):
    return "error: params must be an object of key -> value"

  results = []
  for key, value in updates.items():
    key = str(key)
    if is_control_param(key):
      results.append(f"{key}: REFUSED - vehicle-control parameter (hard blacklist)")
      continue
    if key not in WRITE_PARAM_WHITELIST:
      results.append(f"{key}: REFUSED - not on the writable whitelist")
      continue
    if is_offroad(params_dir):  # re-check between keys (cheap, belt-and-suspenders)
      coerced = coerce_bool_value(value)
      if coerced is None:
        results.append(f"{key}: REFUSED - not a valid bool value ({value!r})")
        continue
      write_param_file(params_dir, key, coerced)
      results.append(f"{key}: written")
    else:
      results.append(f"{key}: REFUSED - offroad state changed mid-call")
  return "\n".join(results)


def tool_upload_logs(arguments: dict, params_dir: str) -> str:
  """Report the uploader's pending queue and optionally prioritise a route.

  Walks the same channel system/loggerd/uploader.py uses: a file counts as
  pending when it lacks the user.upload xattr, and a locked route dir is
  skipped exactly like the uploader skips it. The optional ``route`` argument
  writes into AthenadRecentlyViewedRoutes - the uploader's existing priority
  channel (it keeps qcamera uploads alive for those routes on metered links);
  this tool never uploads anything itself.
  """
  if not is_offroad(params_dir):
    return "error: vehicle is onroad (or state unknown) - upload requests are allowed only while parked"

  has_xattr = hasattr(os, "getxattr")
  pending = 0
  pending_bytes = 0
  per_route: list[str] = []
  try:
    route_dirs = sorted(os.listdir(ROUTE_DIR), reverse=True)
  except OSError as exc:
    return f"error: cannot list routes: {exc}"
  for logdir in route_dirs:
    path = os.path.join(ROUTE_DIR, logdir)
    if not os.path.isdir(path):
      continue
    try:
      names = os.listdir(path)
    except OSError:
      continue
    if any(name.endswith(".lock") for name in names):  # uploader skips locked dirs too
      continue
    count = 0
    size = 0
    for name in names:
      fn = os.path.join(path, name)
      if not os.path.isfile(fn):
        continue
      if has_xattr:
        try:
          if os.getxattr(fn, UPLOAD_XATTR_NAME) == UPLOAD_XATTR_VALUE:
            continue
        except OSError:
          pass  # attribute unreadable/unset -> treat as pending
      count += 1
      try:
        size += os.path.getsize(fn)
      except OSError:
        pass
    if count:
      pending += count
      pending_bytes += size
      per_route.append(f"{logdir}: {count} file(s)")
      if len(per_route) >= 10:
        break

  suffix = "" if has_xattr else " (xattr unavailable here - every file counted, may overcount)"
  lines = [
    f"pending uploads: {pending} file(s){suffix}",
    f"pending size: {pending_bytes / (1 << 20):.1f} MiB",
  ]
  if per_route:
    lines.append("routes with pending files:")
    lines.extend(f"  {entry}" for entry in per_route)

  route = arguments.get("route")
  if route is not None:
    route = str(route).strip()
    if not ROUTE_NAME_RE.match(route):
      lines.append("route request: REFUSED - route name must match [A-Za-z0-9_-]+")
    else:
      try:
        existing = read_param_file(params_dir, "AthenadRecentlyViewedRoutes") or ""
        entries = [entry for entry in existing.split(",") if entry and entry != route]
        entries.insert(0, route)
        write_param_file(params_dir, "AthenadRecentlyViewedRoutes", ",".join(entries[:MAX_ROUTE_ENTRIES]))
        lines.append(f"route request: '{route}' queued for priority upload (uploader picks it up on its next pass)")
      except OSError as exc:
        lines.append(f"route request: failed - {exc}")
  return "\n".join(lines)


def tool_reboot_device(arguments: dict, params_dir: str) -> str:
  if not is_offroad(params_dir):
    return "error: vehicle is onroad (or state unknown) - reboot refused while driving"
  # Same mechanism the carrot web panel's reboot toggle uses.
  write_param_file(params_dir, "DoReboot", "1")
  return "reboot requested via DoReboot param"


TOOLS = [
  {
    "name": "read_logs",
    "description": "Read the last N lines of the system journal (openpilot and services logs).",
    "inputSchema": {
      "type": "object",
      "properties": {"lines": {"type": "integer", "description": f"max lines, default 100, cap {MAX_LINES}"}},
    },
  },
  {
    "name": "dmesg",
    "description": "Read the last N lines of the kernel ring buffer.",
    "inputSchema": {
      "type": "object",
      "properties": {"lines": {"type": "integer", "description": f"max lines, default 100, cap {MAX_LINES}"}},
    },
  },
  {
    "name": "system_stats",
    "description": "Memory, load, disk usage, thermal temperatures and the current offroad flag.",
    "inputSchema": {"type": "object", "properties": {}},
  },
  {
    "name": "list_routes",
    "description": "List recorded route directories, newest first.",
    "inputSchema": {
      "type": "object",
      "properties": {"count": {"type": "integer", "description": "max routes, default 20, cap 100"}},
    },
  },
  {
    "name": "get_params",
    "description": f"Read whitelisted device params. Allowed: {', '.join(sorted(READ_PARAM_WHITELIST))}",
    "inputSchema": {
      "type": "object",
      "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
      "required": ["keys"],
    },
  },
  {
    "name": "set_params",
      "description": (
        "Write whitelisted device params after user approval. Offroad only. "
        + f"Allowed: {', '.join(sorted(WRITE_PARAM_WHITELIST))}. "
        + "Vehicle-control parameters are hard-refused."
      ),
    "inputSchema": {
      "type": "object",
      "properties": {"params": {"type": "object", "additionalProperties": True}},
      "required": ["params"],
    },
  },
  {
    "name": "upload_logs",
    "description": (
      "Report pending route-log uploads (what system/loggerd/uploader.py will send and why it may be stalled)"
      + " and optionally prioritise one route via the 'route' argument. Offroad only, requires user approval."
    ),
    "inputSchema": {
      "type": "object",
      "properties": {"route": {"type": "string", "description": "route name to prioritise (optional)"}},
    },
  },
  {
    "name": "reboot_device",
    "description": "Reboot the device (offroad only, requires user approval).",
    "inputSchema": {"type": "object", "properties": {}},
  },
]

TOOL_HANDLERS = {
  "read_logs": tool_read_logs,
  "dmesg": tool_dmesg,
  "system_stats": tool_system_stats,
  "list_routes": tool_list_routes,
  "get_params": tool_get_params,
  "set_params": tool_set_params,
  "upload_logs": tool_upload_logs,
  "reboot_device": tool_reboot_device,
}


# ── JSON-RPC / MCP plumbing ──────────────────────────────────────────────────

def handle_request(request: dict, params_dir: str) -> dict | None:
  method = request.get("method", "")
  request_id = request.get("id")
  is_notification = request_id is None
  params = request.get("params") or {}

  def result(payload: dict) -> dict | None:
    if is_notification:
      return None
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}

  def error(code: int, message: str) -> dict | None:
    if is_notification:
      return None
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

  if method == "initialize":
    return result({
      "protocolVersion": PROTOCOL_VERSION,
      "capabilities": {"tools": {}},
      "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })
  if method in ("notifications/initialized", "notifications/cancelled", "ping"):
    return result({})
  if method == "tools/list":
    return result({"tools": TOOLS})
  if method == "tools/call":
    name = str(params.get("name") or "")
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
      return error(-32602, f"unknown tool: {name}")
    try:
      text = handler(params.get("arguments") or {}, params_dir)
      is_error = text.startswith("error:")
      if is_error:
        text = text[len("error:"):].strip()
      return result({
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
      })
    except Exception as exc:  # surface tool errors, never crash the server
      return result({"content": [{"type": "text", "text": f"tool {name} failed: {type(exc).__name__}: {exc}"}], "isError": True})
  return error(-32601, f"method not supported: {method}")


def serve(stdin=None, stdout=None, params_dir: str = "/data/params/d") -> None:
  """Serve MCP over line-delimited JSON on stdio. Exposed for tests."""
  stdin = stdin if stdin is not None else sys.stdin
  stdout = stdout if stdout is not None else sys.stdout
  for line in stdin:
    line = line.strip()
    if not line:
      continue
    try:
      request = json.loads(line)
    except ValueError:
      continue
    response = handle_request(request, params_dir)
    if response is not None:
      stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
      stdout.flush()


if __name__ == "__main__":
  serve()
