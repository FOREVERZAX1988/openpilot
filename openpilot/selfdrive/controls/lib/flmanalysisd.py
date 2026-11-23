#!/usr/bin/env python3
"""flmanalysisd: resident FLM analysis daemon (F3 + F2 param contract).

Trigger/status contract (F2, UI-facing):
- ``FLMAnalysisRequested`` (BOOL): the UI sets it true; the daemon consumes it
  (auto-discovers the latest route) and clears it back to false itself.
- ``FLMAnalysisStatus`` (STRING): the daemon writes a short JSON
  ``{"state": "idle|collecting|fitting|accepted|rolled_back|error",
  "detail": "...", "ts": <unix>}`` on every state change. The UI only reads
  this param and only writes the trigger param.

On a trigger or on a slow periodic cadence while offroad, the daemon runs the
flm_workspace analysis entry (``analyze_routes``) in-process. Results are
published the same way the UI-triggered worker publishes them: the workspace
report files, the ``/tmp/galaxy_flm_status.json`` status blob (via
flm_workspace), the ``FLMAnalysisStatus`` param above, and a merged
``FLMActiveOverrides`` override bundle.

Deliberate scope limits:

- The daemon only merges the selected profile's ``flmOverrides`` (friction
  thresholds / vehicle knobs / control effects) into ``FLMActiveOverrides``.
  It never touches ``FLMTrialApplied`` / snapshot / rollback state, so the
  panel's trial apply/revert flows keep working unchanged.
- Nothing is written unless ``analyze_routes`` completed a report. Every loop
  iteration is exception-guarded: an analysis failure is logged and retried on
  the next cadence, never crashes the daemon (manager restarts it anyway via
  ``restart_if_crash=True``, but the loop itself is designed not to die).
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

# Periodic re-analysis cadence: every 6 hours, offroad only (task F3:
# "周期性（每 N 小时且 offroad）"). On-demand triggers are honored any time the
# car is offroad.
FLM_ANALYSIS_PERIOD_SECONDS = 6 * 3600
FLM_LOOP_INTERVAL_SECONDS = 10.0
FLM_AUTO_ROUTE_LIMIT = 1  # auto-discovery picks the most recent route only
FLM_STATUS_PATH = Path("/tmp/galaxy_flm_status.json")


def _cloudlog():
  from openpilot.common.swaglog import cloudlog
  return cloudlog


def _flm_modules():
  # Imported lazily: flm_workspace pulls in the capnp/torqued chain, which is
  # only present after the scons build; a failure here must not kill the loop.
  from openpilot.selfdrive.controls.lib import flm_workspace
  return flm_workspace


def _set_status(params, state: str, detail: str) -> None:
  """F2 contract: short JSON state line into the FLMAnalysisStatus param."""
  # The contract mandates a wall-clock unix ts, so time.time (not monotonic).
  payload = json.dumps({"state": state, "detail": str(detail), "ts": time.time()},  # noqa: TID251
                       separators=(",", ":"))
  params.put("FLMAnalysisStatus", payload)


def _offroad(params) -> bool:
  return not params.get_bool("IsOnroad")


def _discover_latest_routes(footage_paths: list[str], limit: int = FLM_AUTO_ROUTE_LIMIT) -> list[str]:
  """Most-recent route names found under the footage roots (auto mode)."""
  route_dirs: list[Path] = []
  for root in footage_paths:
    root_path = Path(root)
    if not root_path.is_dir():
      continue
    for entry in root_path.iterdir():
      if entry.is_dir() and "--" in entry.name:
        try:
          route_dirs.append((entry.stat().st_mtime, entry.name))
        except OSError:
          continue
  route_dirs.sort(reverse=True)
  routes: list[str] = []
  for _, name in route_dirs:
    route = name.rsplit("--", 1)[0]
    if route and route not in routes:
      routes.append(route)
    if len(routes) >= limit:
      break
  return routes


def _extract_primary_flm_overrides(report: dict[str, Any]) -> dict[str, Any]:
  """The selected profile's flmOverrides from the primary tuning path."""
  for path_payload in report.get("paths", []) or []:
    if not isinstance(path_payload, dict) or not path_payload.get("isPrimary"):
      continue
    for profile in path_payload.get("profiles", []) or []:
      if not isinstance(profile, dict):
        continue
      overrides = profile.get("flmOverrides")
      if isinstance(overrides, dict) and overrides:
        return overrides
  return {}


def _auto_apply_overrides(params, report: dict[str, Any]) -> dict[str, Any]:
  """Merge the report's primary flmOverrides into FLMActiveOverrides.

  Conservative by design: only the override bundle is merged (the controller
  re-admits it through FlmOverrideOwner, which re-validates everything against
  the stock baseline band). Generic panel params and the trial/rollback state
  are intentionally untouched.
  """
  flm = _flm_modules()
  overrides = _extract_primary_flm_overrides(report)
  if not overrides:
    return {"applied": False, "reason": "no_primary_flm_overrides"}

  raw = params.get("FLMActiveOverrides")
  current: Any = None
  if raw:
    try:
      current = json.loads(raw)
    except (ValueError, TypeError):
      current = None

  merged = flm._merge_flm_override_state(current if isinstance(current, dict) else {}, overrides)
  if merged:
    params.put("FLMActiveOverrides", merged)
    params.put_bool("StarPilotTogglesUpdated", True)
  return {"applied": bool(merged), "mergedFamilies": sorted(merged.get("baseFrictionThresholds", {}).keys())}


def _run_analysis(params) -> dict[str, Any]:
  flm = _flm_modules()
  footage_paths = flm.get_flm_footage_paths()
  routes = _discover_latest_routes(footage_paths)
  if not routes:
    return {"state": "error", "detail": "no_routes", "routes": []}

  report = flm.analyze_routes(routes, footage_paths)
  apply_state = _auto_apply_overrides(params, report)
  if apply_state.get("applied"):
    return {
      "state": "accepted",
      "detail": f"report {report.get('reportId', '')} overrides merged",
      "routes": routes,
      "reportId": report.get("reportId", ""),
      "crossCheck": report.get("crossCheck"),
      "apply": apply_state,
    }
  return {
    "state": "error",
    "detail": f"report {report.get('reportId', '')} finished but {apply_state.get('reason', 'nothing_applied')}",
    "routes": routes,
    "reportId": report.get("reportId", ""),
    "crossCheck": report.get("crossCheck"),
    "apply": apply_state,
  }


def main() -> None:
  from openpilot.common.params import Params
  params = Params()
  last_analysis = 0.0
  _set_status(params, "idle", "flmanalysisd started")
  _cloudlog().info("flmanalysisd started")
  while True:
    time.sleep(FLM_LOOP_INTERVAL_SECONDS)
    try:
      requested = params.get_bool("FLMAnalysisRequested")
      periodic_due = _offroad(params) and (time.monotonic() - last_analysis) >= FLM_ANALYSIS_PERIOD_SECONDS
      if not requested and not periodic_due:
        continue

      if not _offroad(params):
        # Consume the trigger even when it cannot run now, so a stale request
        # cannot fire later while driving.
        if requested:
          params.put_bool("FLMAnalysisRequested", False)
        from openpilot.selfdrive.controls.lib.flm_workspace import _write_flm_status
        _write_flm_status({"state": "skipped_onroad", "trigger": "flmanalysisd"})
        continue

      flm = _flm_modules()
      if flm.flm_analyzer_running():
        # A UI-triggered worker subprocess owns the workspace right now.
        if requested:
          params.put_bool("FLMAnalysisRequested", False)
        _cloudlog().info("flmanalysisd: analyzer already running, deferring")
        continue

      if requested:
        params.put_bool("FLMAnalysisRequested", False)
      _set_status(params, "fitting", "analysis started")
      result = _run_analysis(params)
      if result.get("state") == "accepted":
        last_analysis = time.monotonic()
      _set_status(params, result.get("state", "error"), result.get("detail", ""))
      _cloudlog().info(f"flmanalysisd: analysis result {result.get('state')} report={result.get('reportId', '')}")
    except Exception as exc:
      # 异常不崩管理器: log and keep the daemon alive; the periodic cadence or
      # the next trigger will retry.
      _set_status(params, "error", f"{type(exc).__name__}: {exc}")
      _cloudlog().warning(f"flmanalysisd: analysis cycle failed\n{traceback.format_exc()}")


if __name__ == "__main__":
  main()
