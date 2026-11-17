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
  "AgentOpencodeVersion",
  "AgentAutoUpdate",
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
  "AgentAutoUpdate",  # opt-in switch for update_opencode; user-approved in the web panel
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

# opencode runtime updates. The binary is normally pinned by AGNOS
# (userspace/agent_setup.sh); this is the opt-in runtime update channel.
OPENCODE_BIN = "/usr/local/bin/opencode"
OPENCODE_BACKUP_DIR = "/data/opencode_backup"
OPENCODE_STAGING_DIR = "/data/opencode_update"
OPENCODE_RELEASES_API = "https://api.github.com/repos/sst/opencode/releases"
OPENCODE_ASSET = "opencode-linux-arm64.tar.gz"
DOWNLOAD_TIMEOUT_SECONDS = 900

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


# ── opencode runtime update tools ────────────────────────────────────────────

def _parse_version(tag: str) -> tuple[int, ...] | None:
  parts = tag.strip().lstrip("vV").split(".")
  try:
    return tuple(int(p) for p in parts[:3])
  except ValueError:
    return None


def _opencode_version() -> str:
  try:
    proc = subprocess.run([OPENCODE_BIN, "--version"], capture_output=True, encoding="utf-8", errors="replace", timeout=15)
    if proc.returncode == 0 and proc.stdout.strip():
      return proc.stdout.strip().split()[-1]
  except (OSError, subprocess.TimeoutExpired):
    pass
  return "unknown"


def _fetch_releases(count: int = 5) -> list[dict]:
  import urllib.request
  req = urllib.request.Request(
    f"{OPENCODE_RELEASES_API}?per_page={count}",
    headers={"User-Agent": "comma-agent", "Accept": "application/vnd.github+json"},
  )
  with urllib.request.urlopen(req, timeout=30) as resp:
    return json.load(resp)


def _asset_for(release: dict) -> dict | None:
  for asset in release.get("assets") or []:
    if asset.get("name") == OPENCODE_ASSET:
      return asset
  return None


def tool_check_opencode_update(arguments: dict, params_dir: str) -> str:
  """Read-only: current binary version vs the most recent upstream releases."""
  current = _opencode_version()
  cur = _parse_version(current)
  try:
    releases = _fetch_releases()
  except Exception as exc:
    return f"error: cannot reach GitHub releases API: {type(exc).__name__}: {exc}"
  lines = [f"installed: {current}", "recent upstream releases:"]
  for release in releases:
    tag = release.get("tag_name") or "?"
    asset = _asset_for(release)
    newer = ""
    if cur and _parse_version(tag):
      newer = " (newer than installed)" if _parse_version(tag) > cur else ""
    lines.append(f"  {tag}{' [pre-release]' if release.get('prerelease') else ''}"
                 f"{' [no arm64 asset]' if asset is None else ''}{newer}")
  lines.append("to update: confirm with the user, set the AgentAutoUpdate param (needs their approval), then call update_opencode with the exact tag.")
  return "\n".join(lines)


def tool_update_opencode(arguments: dict, params_dir: str) -> str:
  if not is_offroad(params_dir):
    return "error: vehicle is onroad (or state unknown) - updates are allowed only while parked"
  if read_param_file(params_dir, "AgentAutoUpdate") != "1":
    return "error: AgentAutoUpdate param is not enabled - ask the user to enable it (set_params AgentAutoUpdate=1) before updating"

  target = str(arguments.get("version") or "").strip()
  tgt = _parse_version(target)
  if not target.startswith("v") or tgt is None:
    return "error: 'version' must be an exact release tag like 'v2.3.1'"

  current = _opencode_version()
  cur = _parse_version(current)
  if cur is None:
    return f"error: cannot determine installed version ({current!r}) - refusing to overwrite"
  if tgt <= cur:
    return f"error: refusing to downgrade or reinstall (installed {current}, target {target})"

  import shutil
  import tarfile
  try:
    release = next((r for r in _fetch_releases(20) if r.get("tag_name") == target), None)
    if release is None:
      return f"error: release {target} not found in the last 20 upstream releases"
    asset = _asset_for(release)
    if asset is None:
      return f"error: release {target} has no {OPENCODE_ASSET} asset"
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
      return "error: release asset has no sha256 digest - refusing to install an unverified binary"

    os.makedirs(OPENCODE_STAGING_DIR, exist_ok=True)
    os.makedirs(OPENCODE_BACKUP_DIR, exist_ok=True)
    tarball = os.path.join(OPENCODE_STAGING_DIR, OPENCODE_ASSET)
    import urllib.request
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "comma-agent"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp, open(tarball, "wb") as out:
      shutil.copyfileobj(resp, out)
    actual = _sha256_file(tarball)
    if actual != digest.split(":", 1)[1]:
      return f"error: sha256 mismatch (expected {digest.split(':', 1)[1][:16]}..., got {actual[:16]}...) - staged file deleted"
  except Exception as exc:
    return f"error: download failed: {type(exc).__name__}: {exc}"

  # Backup then install. sudo is NOPASSWD on AGNOS; install needs root because
  # /usr/local/bin is root-owned.
  backup = os.path.join(OPENCODE_BACKUP_DIR, f"opencode.{current}")
  try:
    shutil.copy2(OPENCODE_BIN, backup)
  except OSError as exc:
    return f"error: cannot back up current binary: {exc}"

  extract_dir = os.path.join(OPENCODE_STAGING_DIR, "unpack")
  installed = False
  try:
    shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir)
    with tarfile.open(tarball) as tf:
      tf.extractall(extract_dir)  # noqa: S202 - tarball sha256-verified against the release digest
      members = os.listdir(extract_dir)
      binary_name = "opencode" if "opencode" in members else (members[0] if members else "")
      new_binary = os.path.join(extract_dir, binary_name)
      if not binary_name or not os.path.isfile(new_binary):
        return "error: tarball layout unexpected - no opencode binary found; backup untouched"
    proc = subprocess.run(
      ["sudo", "-n", "install", "-m", "0755", new_binary, OPENCODE_BIN],
      capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if proc.returncode != 0:
      return f"error: install failed: {(proc.stderr or proc.stdout).strip()[:200]}; backup at {backup}"
    installed = True
  finally:
    shutil.rmtree(OPENCODE_STAGING_DIR, ignore_errors=True)

  # Post-install validation with automatic rollback.
  new_version = _opencode_version()
  if new_version != target.lstrip("v") and new_version != target:
    subprocess.run(["sudo", "-n", "install", "-m", "0755", backup, OPENCODE_BIN], capture_output=True, timeout=60)
    return f"error: new binary reports {new_version!r} instead of {target} - rolled back to {current}"
  return (
    f"updated opencode {current} -> {target} (backup at {backup}). "
    + ("Restart the AI agent (toggle it off/on in settings, or reboot) to run the new version."
       if installed else "")
  )


def _sha256_file(path: str) -> str:
  import hashlib
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
      h.update(chunk)
  return h.hexdigest()


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
  {
    "name": "check_opencode_update",
    "description": "Compare the installed opencode version against recent upstream releases (read-only, no changes).",
    "inputSchema": {"type": "object", "properties": {}},
  },
  {
    "name": "update_opencode",
    "description": (
      "Update the opencode binary to a specific newer release tag. Offroad only, "
      "requires the AgentAutoUpdate param enabled (user-approved) and the user's explicit "
      "confirmation of the target version. Verifies the sha256 digest and rolls back on failure."
    ),
    "inputSchema": {
      "type": "object",
      "properties": {"version": {"type": "string", "description": "exact release tag, e.g. 'v2.3.1'"}},
      "required": ["version"],
    },
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
  "check_opencode_update": tool_check_opencode_update,
  "update_opencode": tool_update_opencode,
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
