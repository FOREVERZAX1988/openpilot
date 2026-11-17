# Device Environment & Agent Operations (AGNOS / comma 3X)

Ground rules for working on THIS device. The project tree at /data/openpilot is
the live, running openpilot source - changes here affect the car after a restart.

## Your capabilities tier (AgentWorkshopMode param)

- `""` (read-only): diagnose only. Use the comma-tools MCP tools below.
- `edit`: you may edit files inside /data/openpilot (everything outside is
  fenced). Every shell command requires explicit user approval.
- `full`: shell allowed. You run as ROOT on the car's computer. Behave like a
  production SRE: explain destructive commands first, keep changes minimal,
  leave a `git diff` the owner can review or revert.

## comma-tools MCP tools (device control goes ONLY through these)

| Tool | Purpose | Gate |
|------|---------|------|
| read_logs / dmesg | journal + kernel ring, quote real lines | read |
| system_stats | mem/load/disk/temps/offroad flag | read |
| list_routes | recorded drives under /data/media/0/realdata | read |
| get_params | whitelisted params only | read |
| set_params | whitelisted params, offroad only, user approval | write |
| upload_logs | uploader queue status; prioritise a route | offroad |
| reboot_device | via DoReboot param | offroad |
| check_opencode_update / update_opencode | opencode binary channel | offroad + opt-in |

Writes are refused onroad and for vehicle-control keys (blacklist in
sunnypilot/agent/comma_mcp.py: LongitudinalTuning, LateralTuning, MADS,
Personality, ExperimentalMode, ...). Never try to work around that blacklist -
it is the car's safety boundary, not an inconvenience.

## AGNOS facts that bite

- `/` is read-only; `/data` is read-write and survives reboot. Patching system
  files needs `sudo remount-rw` (or `mount -o remount,rw /`) and gets reverted
  by OTA.
- `/tmp` is a small tmpfs - it fills fast. Use `/data/tmp` for scratch space.
- Params are files under `/data/params/d/<Key>`. Python reads them via
  `openpilot/common/params.py`; only keys registered in
  `openpilot/common/params_keys.h` are accepted by libparams - a get() on an
  unregistered key raises UnknownKeyName. Writing a raw file into
  `/data/params/d/` works for keys registered in the RUNNING build.
- Git over HTTPS: the device has no CA certificates; clones need
  `-c http.sslVerify=false` (LAN mirrors only, never for untrusted origins).
- Network manager owns WiFi; if WiFi is unconfigured the device is unreachable
  except by serial console. `nmcli` is available for diagnosis.
- SSH: `comma@<ip>` (password in ~/.ssh/comma_info or comma's standard
  credentials); `sudo` is NOPASSWD.
- `pkill -f <pattern>` from an SSH session matches the SSH command line itself.
  Exclude your own session: `pkill -f "[p]attern"`.

## Troubleshooting playbooks (field-proven)

1. `ModuleNotFoundError: No module named 'opendbc'` (or panda/tinygrad):
   a submodule's checkout silently failed - HEAD points at the right sha and
   `git submodule status` says OK, but the worktree is empty. Verify with
   file counts, then `git submodule update --init <path> && git -C <path>
   checkout -f HEAD`. Never trust submodule status alone after a shallow
   update.
2. Frame drops / lag complaints: judge by `frameDropPerc` in
   `qlog`/services logs first, NOT by CPU% - CPU is noisy on a road unit.
3. Device unreachable: direct WiFi IP -> scan current subnet -> check the
   subnet it actually joined (SSID change) -> serial console. Never conclude
   "dead" before the serial step.
4. openpilot won't start after a hot-patch: reproduce the exact import failure
   in the manager's environment
   (`PYTHONPATH=/data/openpilot:/usr/local/venv/lib/python3.12/site-packages:/data/.pydeps /usr/bin/python3 -c "import ..."`)
   before touching anything else.
5. Tailscale login URL dies after ~10 min: `tailscale up` rotates the login
   session on every call. Broadcast the URL from `tailscale status`
   ("Log in at:") instead of re-running `up`.

## Hard safety lines (never cross)

- Never modify `opendbc_repo/opendbc/safety/` logic without the full test
  suite + 100% coverage passing.
- Never disable driver monitoring or excessive actuation checks.
- Never write vehicle-control params (they are hard-refused anyway).
- Anything beyond /data/openpilot edits requires explaining and, where the
  tier supports it, user-visible approval.
