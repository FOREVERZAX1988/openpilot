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
_car.car.structs.car.CarState = _FakeCarState
# Saved and restored around the module exec below; a stub left in sys.modules would make
# every later test module in the same process see a fake opendbc (see test_carrot_man.py).
_SAVED_MODULES = {name: sys.modules.get(name) for name in (
  "opendbc", "opendbc.car", "opendbc.car.structs", "opendbc.car.structs.car",
)}
sys.modules["opendbc"] = _car
sys.modules["opendbc.car"] = _car.car
sys.modules["opendbc.car.structs"] = _car.car.structs
sys.modules["opendbc.car.structs.car"] = _car.car.structs.car

_SRC = pathlib.Path(__file__).resolve().parent.parent / "carrot_navi_fusion.py"
_spec = importlib.util.spec_from_file_location("carrot_navi_fusion_under_test", _SRC)
carrot_navi_fusion = importlib.util.module_from_spec(_spec)
sys.modules["carrot_navi_fusion_under_test"] = carrot_navi_fusion
_spec.loader.exec_module(carrot_navi_fusion)

for _name, _module in _SAVED_MODULES.items():
  if _module is None:
    sys.modules.pop(_name, None)
  else:
    sys.modules[_name] = _module
del _name, _module


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


class TestNavLaneGuideBlocks(unittest.TestCase):
  """7706 navLaneGuide -> lane blocking (App field list §2.2)."""

  def test_left_only_guidance_blocks_right(self):
    left, right = carrot_navi_fusion.nav_lane_guide_blocks("L,SL")
    self.assertFalse(left)
    self.assertTrue(right)

  def test_right_only_guidance_blocks_left(self):
    left, right = carrot_navi_fusion.nav_lane_guide_blocks("R")
    self.assertTrue(left)
    self.assertFalse(right)

  def test_both_directions_constrain_neither(self):
    left, right = carrot_navi_fusion.nav_lane_guide_blocks("L,R")
    self.assertFalse(left)
    self.assertFalse(right)

  def test_straight_only_constrains_neither(self):
    left, right = carrot_navi_fusion.nav_lane_guide_blocks("S")
    self.assertFalse(left)
    self.assertFalse(right)

  def test_json_array_payload_is_parsed(self):
    left, right = carrot_navi_fusion.nav_lane_guide_blocks('["L","SL"]')
    self.assertFalse(left)
    self.assertTrue(right)

  def test_empty_or_malformed_is_noop(self):
    for payload in ("", None, "[]", "not json", "  "):
      self.assertEqual(carrot_navi_fusion.nav_lane_guide_blocks(payload), (False, False))

  def test_truncated_array_is_rejected(self):
    # Declared 3 entries but only 2 present -> discard rather than guess.
    left, right = carrot_navi_fusion.nav_lane_guide_blocks("L,SL", declared_count=3)
    self.assertFalse(left)
    self.assertFalse(right)

  def test_matching_count_is_accepted(self):
    left, right = carrot_navi_fusion.nav_lane_guide_blocks("L,SL", declared_count=2)
    self.assertFalse(left)
    self.assertTrue(right)


class TestNavLaneGuideMerge(unittest.TestCase):
  """The 7706 guide must share the one merge path and only ever add blocking."""

  def test_gate_off_means_no_effect(self):
    cs_sp = _FakeCarStateSP()
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, None, "L,SL", 2, use_nav_lane_guide=False)
    self.assertFalse(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertFalse(cs_sp.carrotRightLineBlocked)

  def test_gate_on_blocks_without_7714_data(self):
    cs_sp = _FakeCarStateSP()
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, None, "L,SL", 2, use_nav_lane_guide=True)
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertTrue(cs_sp.carrotRightLineBlocked)

  def test_guide_adds_to_7714_result(self):
    cs_sp = _FakeCarStateSP()
    lane = _make_lane(count=3, current_lane=2, available=[1, 1, 1])
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane), "L", 1, use_nav_lane_guide=True)
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertTrue(cs_sp.carrotRightLineBlocked)

  def test_guide_never_clears_a_7714_block(self):
    cs_sp = _FakeCarStateSP()
    # 7714 says the right lane is unavailable.
    lane = _make_lane(count=3, current_lane=2, available=[1, 1, 0])
    # Guide steers right, which would "allow" the right side on its own.
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, _make_carrot_navi(lane), "R", 1, use_nav_lane_guide=True)
    self.assertTrue(cs_sp.carrotRightLineBlocked, "guide must not clear the 7714 block")

  def test_no_guide_and_no_navi_clears_all(self):
    cs_sp = _FakeCarStateSP()
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, None, "", 0, use_nav_lane_guide=True)
    self.assertFalse(cs_sp.carrotLaneValid)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)
    self.assertFalse(cs_sp.carrotRightLineBlocked)


class _FakeLaneHD:
  def __init__(self, **kw):
    self.available = kw.get("available", False)
    self.hd = kw.get("hd", False)
    self.laneCount = kw.get("laneCount", 0)
    self.totalLaneCntConf = kw.get("totalLaneCntConf", 0.0)
    self.curLaneIdx0 = kw.get("curLaneIdx0", -1)
    self.curLaneNumConf = kw.get("curLaneNumConf", 0.0)
    self.slope = kw.get("slope", 0.0)
    self.leftBlocked = kw.get("leftBlocked", False)
    self.rightBlocked = kw.get("rightBlocked", False)


def _make_lane_with_meta(count: int, current_lane: int, available: list[int],
                         received_age_s: float = 0.1, present: bool = True):
  """Lane whose item received time sits `received_age_s` behind the publish clock."""

  navi = _make_carrot_navi(_make_lane(count=count, current_lane=current_lane, available=available, present=present))
  navi.laneHD = _FakeLaneHD(available=True)
  navi.publishMonoTimeNanos = 1_000_000_000 * 10  # any fixed point
  if navi.laneCurrent is not None:
    navi.laneCurrent.meta.receivedMonoTimeNanos = navi.publishMonoTimeNanos - int(received_age_s * 1e9)
  return navi


class TestHdLaneState(unittest.TestCase):
  """HD lane match (lane_current.value.hd -> carrotNaviSP.laneHD)."""

  def _hd_state(self, navi):
    return carrot_navi_fusion.hd_lane_state(navi)

  def test_none_navi_is_unusable(self):
    self.assertFalse(self._hd_state(None)["usable"])

  def test_missing_laneHD_is_unusable(self):
    navi = _make_carrot_navi(_make_lane(count=3, current_lane=2, available=[1, 1, 1]))
    self.assertFalse(self._hd_state(navi)["usable"])

  def test_valid_hd_state(self):
    navi = _make_lane_with_meta(count=4, current_lane=2, available=[1, 1, 1, 1])
    navi.laneHD = _FakeLaneHD(available=True, hd=True, laneCount=4, totalLaneCntConf=0.9,
                              curLaneIdx0=1, curLaneNumConf=0.85, leftBlocked=True, rightBlocked=False)
    state = self._hd_state(navi)
    self.assertTrue(state["usable"])
    self.assertEqual(state["curLaneIdx0"], 1)
    self.assertEqual(state["laneCount"], 4)
    self.assertTrue(state["leftBlocked"])
    self.assertFalse(state["rightBlocked"])

  def test_stale_item_is_unusable(self):
    navi = _make_lane_with_meta(count=4, current_lane=2, available=[1, 1, 1, 1], received_age_s=5.0)
    navi.laneHD = _FakeLaneHD(available=True, laneCount=4, totalLaneCntConf=0.9,
                              curLaneIdx0=1, curLaneNumConf=0.85)
    self.assertFalse(self._hd_state(navi)["usable"])

  def test_low_confidence_is_unusable(self):
    navi = _make_lane_with_meta(count=4, current_lane=2, available=[1, 1, 1, 1])
    navi.laneHD = _FakeLaneHD(available=True, laneCount=4, totalLaneCntConf=0.9,
                              curLaneIdx0=1, curLaneNumConf=0.2)
    self.assertFalse(self._hd_state(navi)["usable"])

    navi.laneHD = _FakeLaneHD(available=True, laneCount=4, totalLaneCntConf=0.1,
                              curLaneIdx0=1, curLaneNumConf=0.9)
    self.assertFalse(self._hd_state(navi)["usable"])

  def test_out_of_range_lane_index_is_unusable(self):
    navi = _make_lane_with_meta(count=4, current_lane=2, available=[1, 1, 1, 1])
    navi.laneHD = _FakeLaneHD(available=True, laneCount=4, totalLaneCntConf=0.9,
                              curLaneIdx0=4, curLaneNumConf=0.9)
    self.assertFalse(self._hd_state(navi)["usable"])

    navi.laneHD = _FakeLaneHD(available=True, laneCount=4, totalLaneCntConf=0.9,
                              curLaneIdx0=-1, curLaneNumConf=0.9)
    self.assertFalse(self._hd_state(navi)["usable"])


class TestHdLaneMerge(unittest.TestCase):
  """HD blocking joins the additive rule and never clears existing blocks."""

  def test_hd_blocks_add_without_lane_data(self):
    cs_sp = _FakeCarStateSP()
    navi = _make_lane_with_meta(count=0, current_lane=0, available=[], present=False)
    navi.laneHD = _FakeLaneHD(available=True, hd=True, laneCount=4, totalLaneCntConf=0.9,
                              curLaneIdx0=1, curLaneNumConf=0.85, leftBlocked=True, rightBlocked=False)
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, navi)
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertTrue(cs_sp.carrotLeftLineBlocked)
    self.assertFalse(cs_sp.carrotRightLineBlocked)

  def test_hd_never_clears_7714_block(self):
    cs_sp = _FakeCarStateSP()
    # 7714 says right unavailable; HD claims right is fine.
    navi = _make_lane_with_meta(count=3, current_lane=2, available=[1, 1, 0])
    navi.laneHD = _FakeLaneHD(available=True, hd=True, laneCount=3, totalLaneCntConf=0.9,
                              curLaneIdx0=1, curLaneNumConf=0.9, rightBlocked=False)
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, navi)
    self.assertTrue(cs_sp.carrotRightLineBlocked, "HD must not clear the 7714 block")

  def test_hd_adds_block_on_top_of_7714(self):
    cs_sp = _FakeCarStateSP()
    navi = _make_lane_with_meta(count=3, current_lane=2, available=[1, 1, 1])
    navi.laneHD = _FakeLaneHD(available=True, hd=True, laneCount=3, totalLaneCntConf=0.9,
                              curLaneIdx0=1, curLaneNumConf=0.9, leftBlocked=True)
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, navi)
    self.assertTrue(cs_sp.carrotLeftLineBlocked)

  def test_hd_unusable_falls_back_to_7714(self):
    cs_sp = _FakeCarStateSP()
    navi = _make_lane_with_meta(count=3, current_lane=2, available=[1, 1, 0])
    navi.laneHD = _FakeLaneHD(available=False)
    carrot_navi_fusion.merge_carrot_navi_lanes(cs_sp, navi)
    self.assertTrue(cs_sp.carrotLaneValid)
    self.assertTrue(cs_sp.carrotRightLineBlocked)
    self.assertFalse(cs_sp.carrotLeftLineBlocked)


class TestLaneHdPayloadCapnpSmoke(unittest.TestCase):
  """Real-schema smoke test (verification-auditor BLOCKER-1 regression).

  Guards against payload key drift: every key in `_lane_hd()` output must be
  an assignable LaneHD field, or capnp dict assignment raises AttributeError
  and kills the whole carrotNaviSP publish loop. Skipped on workstations
  without pycapnp (the codegen'd cereal module needs it); CI and the device
  environment both have pycapnp 2.1.0.
  """

  def setUp(self):
    try:
      from pycapnp import capnp  # noqa: F401
    except ImportError:
      self.skipTest("pycapnp not available on this workstation")

  def test_lane_hd_payload_assigns_cleanly(self):
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[3]
    capnp_path = repo_root / "custom.capnp"
    if not capnp_path.exists():
      self.skipTest(f"custom.capnp not found at {capnp_path}")

    from pycapnp import capnp
    schema = capnp.load(str(capnp_path))

    # Minimal _lane_hd()-shaped payload (keys must all exist on LaneHD).
    lane_hd_payload = {
      "available": True,
      "hd": True,
      "laneCount": 4,
      "totalLaneCntConf": 0.9,
      "curLaneIdx0": 1,
      "curLaneNumConf": 0.85,
      "slope": 0.0,
      "leftBlocked": True,
      "rightBlocked": False,
      "freePosLaneNum": 0,
      "matchedPosValid": True,
      "matchedLatitude": 31.0,
      "matchedLongitude": 121.0,
      "matchedHeadingDeg": 92.0,
    }
    msg = schema.CarrotNaviStateSP.new_message()
    msg.laneHD = lane_hd_payload
    self.assertTrue(msg.laneHD.available)
    self.assertEqual(msg.laneHD.curLaneIdx0, 1)
    self.assertEqual(msg.laneHD.laneCount, 4)
    self.assertTrue(msg.laneHD.leftBlocked)
    self.assertFalse(msg.laneHD.rightBlocked)

    # The degraded path (missing hd object) must also assign cleanly.
    msg2 = schema.CarrotNaviStateSP.new_message()
    msg2.laneHD = {"available": False}
    self.assertFalse(msg2.laneHD.available)


if __name__ == "__main__":
  unittest.main()
