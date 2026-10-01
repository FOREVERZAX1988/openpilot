"""Headless construct+render smoke test for every settings panel in the sidebar.

Why this exists
---------------
Restarting the device left the screen stuck: manager kept respawning ui every
~7s. The cause was a settings panel that only fails when it is actually built --
TripsLayout called self._get_stats(), a method the layout/upstream merge had
dropped, so SettingsLayoutSP.__init__ (which news up every panel on the first
frame) raised and ui exited before drawing.

py_compile, ruff and a diff review all pass on that code. Instantiating and
rendering each panel is what catches it, so that is what this test does: any
panel that raises during __init__/show_event/render is a UI that will not boot.

The same merge dropped `SectionHeadingSP` / `section_heading_sp` out of
system/ui/sunnypilot/widgets/list_view.py while carrot_tuning_items.py kept
importing them, which makes that module raise ImportError the moment a tab page
touches it. So this test also imports the items module, builds every page and
renders a section heading.

Run from the repo root (no display, no capnp needed):

    PYTHONPATH=. python -m openpilot.selfdrive.ui.tests.settings_panels_render_smoke

NOTE: deliberately NOT named test_*.py -- install_stubs() swaps pyray,
openpilot.common.params and the application module out of sys.modules, so pytest
must not collect this into a shared session.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from openpilot.selfdrive.ui.tests.carrot_tuning_render_smoke import (  # noqa: E402
  Rect, install_stubs,
)


def install_panel_stubs() -> None:
  # install_stubs() already provides the permissive ui_state/device/gui_app
  # doubles (flags *and* predicate methods, callable fallbacks for unknown
  # attributes) that these pages need; only reset the param store.
  install_stubs()

  from openpilot.common.params import store as param_store
  param_store.clear()


def panel_factories():
  """(label, factory) for every value in SettingsLayoutSP._panels plus Carrot tuning."""
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import CarrotTuningLayout

  factories: list[tuple[str, object]] = []

  def add(label: str, module: str, cls: str, *args):
    def make():
      mod = __import__(module, fromlist=[cls])
      return getattr(mod, cls)(*args)
    factories.append((label, make))

  base = "openpilot.selfdrive.ui.layouts.settings"
  sp = "openpilot.selfdrive.ui.sunnypilot.layouts.settings"

  add("Carrot Tuning", f"{sp}.carrot_tuning", "CarrotTuningLayout", None)
  add("Device", f"{sp}.device", "DeviceLayoutSP")
  add("Network", f"{sp}.network", "NetworkUISP", MagicMock())
  add("Bluetooth", f"{sp}.bluetooth_settings", "CarrotBluetoothLayout")
  add("sunnylink", f"{sp}.sunnylink", "SunnylinkLayout")
  add("Toggles", f"{base}.toggles", "TogglesLayout")
  add("Software", f"{sp}.software", "SoftwareLayoutSP")
  add("Models", f"{sp}.models", "ModelsLayout")
  add("Steering", f"{sp}.steering", "SteeringLayout")
  add("Cruise", f"{sp}.cruise", "CruiseLayout")
  add("Visuals", f"{sp}.visuals", "VisualsLayout")
  add("Display", f"{sp}.display", "DisplayLayout")
  add("OSM", f"{sp}.osm", "OSMLayout")
  add("Navigation", f"{sp}.navigation", "NavigationLayout")
  add("Trips", f"{sp}.trips", "TripsLayout")
  add("Vehicle", f"{sp}.vehicle", "VehicleLayout")
  add("Firehose", f"{base}.firehose", "FirehoseLayout")
  add("IMU Calibration", f"{base}.imu_calibration", "ImuCalibrationLayout")
  add("Developer", f"{sp}.developer", "DeveloperLayoutSP")
  add("CarrotTuningLayout class import", f"{sp}.carrot_tuning", "CarrotTuningLayout", None)
  return factories, CarrotTuningLayout


def main() -> int:
  install_panel_stubs()
  factories, _ = panel_factories()

  content = Rect(0, 0, 1600, 900)
  # Tall viewport: panels cull off-screen rows, and we want every row exercised.
  tall = Rect(0, 0, content.width, 6000)

  failures: list[str] = []
  for label, make in factories:
    try:
      layout = make()
      layout.set_parent_rect(content)
      if hasattr(layout, "show_event"):
        layout.show_event()
      layout.render(tall)
      print(f"  ok  {label} constructs + renders")
    except Exception as exc:  # noqa: BLE001
      failures.append(f"{label}: {type(exc).__name__}: {exc}")
      print(f"  FAIL {label}: {type(exc).__name__}: {exc}")

  extra = 0

  def extra_check(label, fn):
    nonlocal extra
    extra += 1
    try:
      fn()
      print(f"  ok  {label}")
    except Exception as exc:  # noqa: BLE001
      failures.append(f"{label}: {type(exc).__name__}: {exc}")
      print(f"  FAIL {label}: {type(exc).__name__}: {exc}")

  def check_section_heading():
    from openpilot.system.ui.sunnypilot.widgets.list_view import section_heading_sp
    heading = section_heading_sp("Group")
    heading.set_parent_rect(content)
    heading.render(tall)

  def check_carrot_tuning_items():
    from openpilot.selfdrive.ui.sunnypilot.layouts.settings import carrot_tuning_items
    builders = sorted(n for n in dir(carrot_tuning_items) if n.startswith("build_"))
    assert builders, "carrot_tuning_items exposes no build_*_items()"
    empty = [n for n in builders if not getattr(carrot_tuning_items, n)()]
    assert not empty, f"these pages build no items: {empty}"
    print(f"        ({len(builders)} Carrot tuning pages build)")

  extra_check("SectionHeadingSP constructs + renders", check_section_heading)
  extra_check("carrot_tuning_items imports + every page builds", check_carrot_tuning_items)

  total = len(factories) + extra
  print(f"\n{total - len(failures)}/{total} panels ok")
  for f in failures:
    print(f"  - {f}")
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
