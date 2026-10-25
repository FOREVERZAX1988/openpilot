"""Headless render smoke test for the sunnypilot Trips settings page.

Why this exists
---------------
TripsLayout crashed the UI in a restart loop with

    AttributeError: 'TripsLayout' object has no attribute '_get_stats'

trips.py called self._get_stats() while the method (and the cloud half of the
page) had been dropped when the layout was flattened against upstream. py_compile
and a diff review both pass on that code -- only actually walking the widget tree
catches it. manager kept respawning ui (exitcode 1) every ~7s, which is what "UI
is stuck" looked like on screen.

A second regression this covers: the page was then "fixed" by clamping the data
source to local-only, which left the Cloud half of the [Local | Cloud] toggle
inert (upstream's works). Both halves must switch the data source and persist
TripsDataSource.

This drives the real module with a fake raylib and a fake gui_app, so
TripsLayout.__init__ -> _get_local_stats and the whole _render path are executed
for real.

Run from the repo root (no display, no capnp needed):

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/trips_render_smoke.py

NOTE: deliberately NOT named test_*.py -- install_stubs() replaces pyray,
openpilot.common.params and openpilot.system.ui.lib.application in sys.modules,
so pytest must not collect it into a shared session.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from openpilot.selfdrive.ui.tests.carrot_tuning_render_smoke import (  # noqa: E402
  DRAWN, Rect, install_stubs,
)

LOCAL_STATS = {
  "all": {"routes": 12, "distance": 143.5, "minutes": 300.0},
  "week": {"routes": 3, "distance": 31.2, "minutes": 55.0},
  "segments": {},
  "updated_at": 0.0,
}
CLOUD_STATS = {
  "all": {"routes": 50, "distance": 900.0, "minutes": 1200.0},
  "week": {"routes": 9, "distance": 120.0, "minutes": 200.0},
}
calls: list[tuple] = []


def install_trips_stubs(store: dict) -> None:
  """Shared stubs + the ui_state/device surface TripsLayout touches."""
  install_stubs()

  # The shared harness only fakes ui_state.is_offroad(); trips.py imports
  # `ui_state, device` and the update thread reads device._awake and
  # ui_state.started.
  mod = types.ModuleType("openpilot.selfdrive.ui.ui_state")
  mod.ui_state = types.SimpleNamespace(started=True)
  mod.device = types.SimpleNamespace(_awake=False)
  sys.modules["openpilot.selfdrive.ui.ui_state"] = mod

  # drive_stats pulls in LogReader/Paths and belongs to a different layer; the
  # layout only needs the two callables to exist.
  ds = types.ModuleType("openpilot.selfdrive.ui.sunnypilot.lib.drive_stats")

  def refresh_local_drive_stats(params, key="LocalDriveStats"):
    calls.append(("local", key))
    params.put(key, LOCAL_STATS)
    return LOCAL_STATS

  def fetch_cloud_drive_stats(params, session=None):
    calls.append(("cloud", session is not None))
    return CLOUD_STATS

  ds.refresh_local_drive_stats = refresh_local_drive_stats
  ds.fetch_cloud_drive_stats = fetch_cloud_drive_stats
  sys.modules["openpilot.selfdrive.ui.sunnypilot.lib.drive_stats"] = ds

  from openpilot.common.params import store as param_store
  param_store.clear()
  param_store.update(store)


def main() -> int:
  install_trips_stubs({"IsMetric": False, "LocalDriveStats": LOCAL_STATS, "TripsDataSource": "local"})
  # install_trips_stubs() copies the seed into the fake params module; that module's
  # store is the one Params() writes to, so read and dump it rather than the seed.
  store = sys.modules["openpilot.common.params"].store

  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.trips import TripsLayout  # noqa: E402

  failures: list[str] = []
  checks = 0

  def check(label, fn):
    nonlocal checks
    checks += 1
    try:
      fn()
      print(f"  ok  {label}")
    except Exception as exc:  # noqa: BLE001
      failures.append(f"{label}: {type(exc).__name__}: {exc}")
      print(f"  FAIL {label}: {type(exc).__name__}: {exc}")

  content = Rect(0, 0, 1600, 900)

  print("== construction (the regression) ==")
  layout = TripsLayout()

  def constructs():
    assert isinstance(layout._stats, dict), f"_stats should be a dict, got {type(layout._stats)}"
    assert layout._stats.get("all"), "stats should survive __init__"

  check("TripsLayout() constructs and seeds _stats", constructs)

  def data_source_defaults_to_local():
    assert layout._data_source == "local", f"expected local, got {layout._data_source!r}"

  check("defaults to the local source", data_source_defaults_to_local)

  print("== render ==")
  layout.set_parent_rect(content)
  layout.show_event()

  def renders():
    DRAWN.clear()
    layout.render(content)
    assert DRAWN, "trips page drew nothing"
    labels = [d[1] for d in DRAWN if isinstance(d[1], str)]
    for expected in ("ALL TIME", "PAST WEEK", "Drives", "Hours", "Local", "Cloud"):
      assert expected in labels, f"{expected!r} not drawn (got {labels[:14]})"

  check("renders without crashing, draws both cards and the toggle", renders)

  def toggle_rects_ready():
    layout.render(content)
    assert layout._local_btn_rect.width > 0, "local toggle rect never laid out"
    assert layout._cloud_btn_rect.width > 0, "cloud toggle rect never laid out"

  check("local/cloud toggle rects are laid out", toggle_rects_ready)

  print("== input: both halves must switch the source ==")

  def tap_cloud_switches_to_cloud():
    layout.render(content)
    c = layout._cloud_btn_rect
    layout._handle_mouse_release(types.SimpleNamespace(x=c.x + c.width / 2, y=c.y + c.height / 2))
    assert layout._data_source == "cloud", f"cloud tap left source at {layout._data_source!r}"
    assert store.get("TripsDataSource") == "cloud", "TripsDataSource was not persisted"

  check("tapping Cloud switches to the cloud source", tap_cloud_switches_to_cloud)

  def cloud_refresh_uses_the_cloud_backend():
    calls.clear()
    layout._refresh_drive_stats()
    assert ("cloud", True) in calls, f"cloud stats never fetched: {calls}"
    assert layout._stats == CLOUD_STATS, f"cloud stats not shown: {layout._stats!r}"

  check("cloud refresh pulls the cloud stats", cloud_refresh_uses_the_cloud_backend)

  def tap_local_switches_back():
    layout.render(content)
    r = layout._local_btn_rect
    layout._handle_mouse_release(types.SimpleNamespace(x=r.x + r.width / 2, y=r.y + r.height / 2))
    assert layout._data_source == "local", f"local tap left source at {layout._data_source!r}"
    assert store.get("TripsDataSource") == "local", "TripsDataSource was not persisted"

  check("tapping Local switches back and refreshes local stats", tap_local_switches_back)

  def stale_cloud_param_is_honoured():
    """A device that already had TripsDataSource='cloud' must not be clamped to local."""
    store["TripsDataSource"] = "cloud"
    fresh = TripsLayout()
    assert fresh._data_source == "cloud", f"stale cloud value coerced to {fresh._data_source!r}"

  check("an existing cloud source is not coerced away", stale_cloud_param_is_honoured)

  print("== empty-stats edge case ==")

  def empty_store_renders():
    store.pop("LocalDriveStats", None)
    store["TripsDataSource"] = "local"
    fresh = TripsLayout()
    assert fresh._stats == {}, f"expected empty stats, got {fresh._stats!r}"
    fresh.set_parent_rect(content)
    DRAWN.clear()
    fresh.render(content)
    assert DRAWN, "layout drew nothing with empty stats"
    labels = [d[1] for d in DRAWN if isinstance(d[1], str)]
    assert "0" in labels, f"expected zeroed values, got {labels[:14]}"

  check("renders with no LocalDriveStats param yet", empty_store_renders)

  print(f"\n{checks - len(failures)}/{checks} checks passed")
  for f in failures:
    print(f"FAILED: {f}")
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
