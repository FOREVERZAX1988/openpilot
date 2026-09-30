"""Headless render smoke test for the sunnypilot Trips settings page.

Why this exists
---------------
TripsLayout crashed the UI in a restart loop with

    AttributeError: 'TripsLayout' object has no attribute '_get_stats'

trips.py:32 called self._get_stats() but the method (and the DATA_SOURCE_PARAM /
LOCAL_KEY class constants) were lost when the layout was flattened against
upstream: the cloud half of the upstream page was dropped while the layout still
referenced it. py_compile and a diff review both pass on that code -- only
actually walking the widget tree catches it. manager kept respawning ui
(exitcode 1) every ~7s, which is what "UI is stuck" looked like on screen.

This drives the real module with a fake raylib and a fake gui_app, so
TripsLayout.__init__ -> _get_stats -> _get_local_stats and the whole _render path
are executed for real.

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

SAMPLE_STATS = {
  "all": {"routes": 12, "distance": 143.5, "minutes": 300.0},
  "week": {"routes": 3, "distance": 31.2, "minutes": 55.0},
  "segments": {},
  "updated_at": 0.0,
}


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
  # layout only needs the callable to exist.
  ds = types.ModuleType("openpilot.selfdrive.ui.sunnypilot.lib.drive_stats")
  ds.refresh_local_drive_stats = lambda params, key="LocalDriveStats": SAMPLE_STATS
  sys.modules["openpilot.selfdrive.ui.sunnypilot.lib.drive_stats"] = ds

  from openpilot.common.params import store as param_store
  param_store.clear()
  param_store.update(store)


def main() -> int:
  store = {"IsMetric": False, "LocalDriveStats": SAMPLE_STATS, "TripsDataSource": "cloud"}
  install_trips_stubs(store)

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

  def data_source_is_local():
    assert layout._data_source == "local", f"expected local-only source, got {layout._data_source!r}"

  check("stale TripsDataSource='cloud' is coerced to local", data_source_is_local)

  print("== render ==")
  layout.set_parent_rect(content)
  layout.show_event()

  def renders():
    DRAWN.clear()
    layout.render(content)
    assert DRAWN, "trips page drew nothing"
    labels = [d[1] for d in DRAWN if isinstance(d[1], str)]
    for expected in ("ALL TIME", "PAST WEEK", "Drives", "Hours"):
      assert expected in labels, f"{expected!r} not drawn (got {labels[:12]})"

  check("renders without crashing and draws both stat cards", renders)

  def toggle_rects_ready():
    layout.render(content)
    assert layout._local_btn_rect.width > 0, "local toggle rect never laid out"
    assert layout._cloud_btn_rect.width > 0, "cloud toggle rect never laid out"

  check("local/cloud toggle rects are laid out", toggle_rects_ready)

  print("== input ==")

  def taps_do_not_crash():
    layout.render(content)
    r = layout._local_btn_rect
    layout._handle_mouse_release(types.SimpleNamespace(x=r.x + r.width / 2, y=r.y + r.height / 2))
    c = layout._cloud_btn_rect
    layout._handle_mouse_release(types.SimpleNamespace(x=c.x + c.width / 2, y=c.y + c.height / 2))
    assert layout._data_source == "local", "tapping the inert Cloud half must not leave the local source"
    assert sys.modules["openpilot.common.params"].store.get("TripsDataSource") != "cloud", \
      "a stale cloud value must not be re-written"

  check("tapping Local is a refresh, tapping Cloud is inert", taps_do_not_crash)

  print("== empty-stats edge case ==")

  def empty_store_renders():
    sys.modules["openpilot.common.params"].store.pop("LocalDriveStats", None)
    fresh = TripsLayout()
    assert fresh._stats == {}, f"expected empty stats, got {fresh._stats!r}"
    fresh.set_parent_rect(content)
    DRAWN.clear()
    fresh.render(content)
    assert DRAWN, "layout drew nothing with empty stats"
    labels = [d[1] for d in DRAWN if isinstance(d[1], str)]
    assert "0" in labels, f"expected zeroed values, got {labels[:12]}"

  check("renders with no LocalDriveStats param yet", empty_store_renders)

  print(f"\n{checks - len(failures)}/{checks} checks passed")
  for f in failures:
    print(f"FAILED: {f}")
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
