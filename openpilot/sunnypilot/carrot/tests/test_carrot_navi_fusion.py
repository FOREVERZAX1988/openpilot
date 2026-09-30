#!/usr/bin/env python3
"""
Offline unit tests for sunnypilot/carrot/carrot_navi_fusion.py.

These tests run WITHOUT building cereal/gen (they avoid importing any
pycapnp-dependent modules), so they can be executed on a stock Windows
workstation.  They verify that lane-change block hints are derived correctly
from the 7714 v2 laneCurrent.available list semantics.
"""
import importlib.util
import pathlib
import sys
import unittest
from types import ModuleType


# Stub opendbc.car.structs so we can import carrot_navi_fusion without
# building the full openpilot tree.
_car = ModuleType("opendbc")
_car.car = ModuleType("opendbc.car")
_car.car.structs = ModuleType("opendbc.car.structs")


class _FakeCarState:
  def __init__(self):
    self.leftBlindspot = False
    self.rightBlindspot = False


class _FakeCarStateSP:
  def __init__(self):
    self.carrotLaneValid = False
    self.carrotLeftLineBlocked = False
    self.carrotRightLineBlocked = False


_car.car.structs.car = ModuleType("opendbc.car.structs.car")

# --- sys.modules stubs are import shims for hosts without a compiled capnp
# runtime. Two things matter for test isolation:
#   1. install them through _install_stub() so tearDownModule() can put the real
#      modules back into sys.modules;
#   2. keep the *package* stubs resolvable: give them the real package __path__,
#      otherwise "import openpilot.common.test" / "opendbc.car.car_helpers" fail
#      with "'x' is not a package" for every test module imported afterwards in
#      the same process (that was the collection error in the combined run).
_LEAKED_SYS_MODULES: dict[str, object] = {}


def _install_stub(name: str, module) -> None:
  # NOTE: these stubs deliberately have no __path__/__spec__. Giving them the real package
  # path makes deeper real imports (e.g. openpilot.common.hardware.base -> openpilot.cereal.log)
  # resolve while the stub is installed, which fails in a different way. Keep the fake a leaf
  # object and just guarantee it is removed again (see tearDownModule) so it cannot leak into
  # other test modules.
  _LEAKED_SYS_MODULES.setdefault(name, sys.modules.get(name))
  sys.modules[name] = module


def _drop_stubs() -> None:
  for _name, _original in _LEAKED_SYS_MODULES.items():
    if _original is None:
      sys.modules.pop(_name, None)
    else:
      sys.modules[_name] = _original
  _LEAKED_SYS_MODULES.clear()


def tearDownModule() -> None:
  _drop_stubs()


_car.car.structs.car.CarState = _FakeCarState
_install_stub("opendbc", _car)
_install_stub("opendbc.car", _car.car)
_install_stub("opendbc.car.structs", _car.car.structs)
_install_stub("opendbc.car.structs.car", _car.car.structs.car)

_SRC = pathlib.Path(__file__).resolve().parent.parent / "carrot_navi_fusion.py"
_spec = importlib.util.spec_from_file_location("carrot_navi_fusion_under_test", _SRC)
carrot_navi_fusion = importlib.util.module_from_spec(_spec)
sys.modules["carrot_navi_fusion_under_test"] = carrot_navi_fusion
_spec.loader.exec_module(carrot_navi_fusion)


def _make_lane(count: int, current_lane: int, available: list[int], present: bool = True):
  class _Meta:
    pass

  meta = _Meta()
  meta.present = present

  class _Lane:
    pass

  lane = _Lane()
  lane.meta = meta
  lane.count = count
  lane.currentLane = current_lane
  lane.available = available
  return lane


def _make_carrot_navi(lane=None):
  class _Navi:
    pass

  navi = _Navi()
  navi.laneCurrent = lane
  return navi


# The shims above only exist to let this module import the code under test. Drop them as soon
# as that import is done so they cannot leak into any other test module (a fake
# 'openpilot.common' module breaks 'import openpilot.common.test' elsewhere).
_drop_stubs()


class TestCarrotNaviLaneFusion(unittest.TestCase):
  def test_no_lane_data_clears_all(self):
    cs_sp = _FakeCarStateSP()
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, None)
    self.assertFalse(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertFalse(cs_sp.carrotRightLineBlocked)

  def test_single_lane_blocks_both_sides(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=1, current_lane=1, available=[1])
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane))
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertTrue(cs_sp.carrotLeftLineBlocked)
    self.assertTrue(cs_sp.carrotRightLineBlocked)

  def test_three_lanes_center_allows_both_sides(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=3, current_lane=2, available=[1, 1, 1])
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane))
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertFalse(cs_sp.carrotRightLineBlocked)

  def test_left_lane_blocks_left_allows_right(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=3, current_lane=1, available=[1, 1, 0])
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane))
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertTrue(cs_sp.carrotLeftLineBlocked)
    self.assertFalse(cs_sp.carrotRightLineBlocked)

  def test_right_lane_blocks_right_allows_left(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=3, current_lane=3, available=[0, 1, 1])
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane))
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertTrue(cs_sp.carrotRightLineBlocked)

  def test_adjacent_unavailable_blocks_side(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=3, current_lane=2, available=[1, 1, 0])
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane))
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertTrue(cs_sp.carrotRightLineBlocked)

  def test_invalid_data_treated_as_blocked(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=3, current_lane=2, available=[1], present=True)
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane))
    self.assertTrue(cs_sp.carrotLaneValid)
    # Right adjacent index (2) is out of available range -> treated blocked.
    self.assertTrue(cs_sp.carrotRightLineBlocked)


if __name__ == "__main__":
  unittest.main()
