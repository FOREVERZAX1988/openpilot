"""Radar point overlay drawing loop (ported from carrot).

Needs a raylib context (``ui_state`` pulls in cereal/opendbc), so this suite runs
on device. The geometry it projects with is covered dependency-free in
``test_radar_display.py``.
"""
import time
import unittest
from types import SimpleNamespace as NS

import numpy as np

from openpilot.selfdrive.ui.sunnypilot.onroad import radar_points
from openpilot.selfdrive.ui.sunnypilot.onroad.radar_points import RadarPointsRenderer
from openpilot.selfdrive.ui.ui_state import ui_state

_RECT = NS(x=0.0, y=0.0, width=2160.0, height=1080.0)


def _point(d_rel=20.0, y_rel=0.0, v_lead=10.0, v_lat=0.0, measured=True, source="frontRadar"):
  # radar_display filters on ``vLead``/``yvRel`` (the published RadarPoint field names);
  # the renderer reads ``vLeadK``/``vLat``. The fixture carries both so the two
  # modules cannot drift apart without a test noticing.
  return NS(trackId=1, dRel=d_rel, yRel=y_rel, vLead=v_lead, yvRel=v_lat, vLeadK=v_lead, vLat=v_lat,
            radar=True, modelProb=0.03, measured=measured, radarSource=source)


def _project(d_rel, y_rel, z):
  return (100.0 + d_rel, 200.0 + y_rel)


def _lane():
  return np.array([[0.0, 0.0, 0.0], [50.0, 0.0, 0.5], [100.0, 0.0, 1.0]], dtype=np.float32)


class _SM:
  """Minimal SubMaster stand-in: only what select_radar_display_points reads."""

  def __init__(self, points, *, seen=True, alive=True, valid=True):
    self._data = NS(points=points, errors=NS(canError=False, radarFault=False, wrongConfig=False,
                                          radarUnavailableTemporary=False, to_dict=dict))
    now = time.monotonic()
    self.seen = {"liveTracks": seen, "modelV2": valid}
    self.alive = {"liveTracks": alive, "modelV2": valid}
    self.valid = {"liveTracks": alive and valid, "modelV2": valid}
    self.recv_time = {"liveTracks": now, "modelV2": now}
    self.recv_frame = {"liveTracks": 5, "modelV2": 5}
    self.logMonoTime = {"liveTracks": now * 1e9, "modelV2": now * 1e9}

  def __getitem__(self, key):
    return self._data if key == "liveTracks" else None


# the box text goes through combined_speed() first, so derive it the same way
SPEED_TEXT = radar_points.speed_text(radar_points.combined_speed(10.0, 0.5)[1], ui_state.is_metric)


class TestRenderLoop(unittest.TestCase):
  def setUp(self):
    self._orig_flag = ui_state.carrot_radar_points
    self._orig_level = ui_state.radar_info_level
    ui_state.radar_info_level = 3
    ui_state.carrot_radar_points = True
    self._orig_rl = radar_points.rl
    self._orig_measure = radar_points.measure_text_cached
    self.calls = []
    self.texts = []
    self._fake = NS(
      Color=lambda *a: ('color',) + a,
      Rectangle=lambda *a: ('rect',) + a,
      # the renderer reads .x/.y off Vector2 to place the shadow copy
      Vector2=lambda x, y: NS(x=x, y=y),
      WHITE=('white',),
      draw_text_ex=lambda font, text, pos, size, spacing, color: (self.calls.append('text'), self.texts.append(text)),
      draw_line_ex=lambda *a: self.calls.append('line'),
      draw_circle=lambda *a: self.calls.append('circle'),
      draw_circle_lines=lambda *a: self.calls.append('ring'),
      draw_rectangle_rounded=lambda *a: self.calls.append('box'),
    )
    radar_points.rl = self._fake
    radar_points.measure_text_cached = lambda font, text, size, spacing=0: NS(x=float(len(text)) * size * 0.5)
    self.renderer = RadarPointsRenderer.__new__(RadarPointsRenderer)
    self.renderer._font = None

  def tearDown(self):
    ui_state.carrot_radar_points = self._orig_flag
    ui_state.radar_info_level = self._orig_level
    radar_points.rl = self._orig_rl
    radar_points.measure_text_cached = self._orig_measure

  def test_disabled_draws_nothing(self):
    ui_state.carrot_radar_points = False
    ui_state.radar_info_level = 0
    self.renderer.render(_SM([_point()]), _RECT, _lane(), _project)
    self.assertEqual(self.calls, [])

  def test_legacy_bool_keeps_full_view(self):
    ui_state.radar_info_level = 0
    ui_state.carrot_radar_points = True
    self.renderer.render(_SM([_point(20.0, -1.0, 10.0, 0.5)]), _RECT, _lane(), _project)
    # every label is drawn twice (shadow + main): speed box, then offset and distance
    self.assertEqual(self.calls, ['line', 'circle', 'box'] + ['text'] * 6)
    self.assertEqual(sorted(self.texts), sorted([SPEED_TEXT, SPEED_TEXT, '-1.0', '-1.0', '20.0', '20.0']))

  def test_level1_draws_speed_box_only(self):
    ui_state.radar_info_level = 1
    self.renderer.render(_SM([_point(20.0, -1.0, 10.0, 0.5)]), _RECT, _lane(), _project)
    self.assertEqual(self.calls, ['line', 'circle', 'box', 'text', 'text'])
    self.assertEqual(self.texts, [SPEED_TEXT, SPEED_TEXT])  # no offset / distance labels

  def test_level2_skips_static_points(self):
    ui_state.radar_info_level = 2
    self.renderer.render(_SM([_point(20.0, 0.0, 0.0, 0.0)]), _RECT, _lane(), _project)
    self.assertEqual(self.calls, [])

  def test_level2_draws_labels_on_moving_points(self):
    ui_state.radar_info_level = 2
    self.renderer.render(_SM([_point(20.0, -1.0, 10.0, 0.5)]), _RECT, _lane(), _project)
    # every label is drawn twice (shadow + main): speed box, then offset and distance
    self.assertEqual(self.calls, ['line', 'circle', 'box'] + ['text'] * 6)
    self.assertEqual(sorted(self.texts), sorted([SPEED_TEXT, SPEED_TEXT, '-1.0', '-1.0', '20.0', '20.0']))

  def test_invalid_model_draws_nothing(self):
    sm = _SM([_point()])
    sm.valid["modelV2"] = False
    self.renderer.render(sm, _RECT, _lane(), _project)
    self.assertEqual(self.calls, [])

  def test_moving_point_draws_vector_then_box(self):
    self.renderer.render(_SM([_point(20.0, -1.0, 10.0, 0.5)]), _RECT, _lane(), _project)
    # every label is drawn twice (shadow + main): speed box, then offset and distance
    self.assertEqual(self.calls, ['line', 'circle', 'box'] + ['text'] * 6)
    self.assertEqual(sorted(self.texts), sorted([SPEED_TEXT, SPEED_TEXT, '-1.0', '-1.0', '20.0', '20.0']))

  def test_slow_point_is_a_star(self):
    self.renderer.render(_SM([_point(20.0, 0.0, 0.0, 0.0)]), _RECT, _lane(), _project)
    self.assertEqual(self.calls, ['text', 'text'])
    self.assertEqual(self.texts, ['*', '*'])

  def test_near_point_is_skipped(self):
    self.renderer.render(_SM([_point(1.0, 0.0, 0.0, 0.0)]), _RECT, _lane(), _project)
    self.assertEqual(self.calls, [])

  def test_unprojectable_point_is_skipped(self):
    self.renderer.render(_SM([_point(20.0, 0.0, 10.0, 0.0)]), _RECT, _lane(), lambda *a: None)
    self.assertEqual(self.calls, [])

  def test_empty_frame_draws_nothing(self):
    self.renderer.render(_SM([]), _RECT, _lane(), _project)
    self.assertEqual(self.calls, [])

  def test_missing_lane_draws_nothing(self):
    self.renderer.render(_SM([_point()]), _RECT, None, _project)
    self.assertEqual(self.calls, [])


if __name__ == "__main__":
  unittest.main()


class TestShowRadarInfoKey(unittest.TestCase):
  """The overlay's level lives in a param that has to be declared INT.

  Declared BOOL it is a silent no-op rather than an error: ``get()`` coerces the
  stored bytes through ``v == b"1"``, so 2 and 3 read back as True/False, and
  ``put_int()`` raises TypeError before anything is written (only int, float and
  str are in PYTHON_2_CPP). Upstream declares this key BOOL and uses it as a
  0-3 level, which is why this class exists: the type is the whole feature.
  """

  def setUp(self):
    from openpilot.common.params import lib
    if lib is None:
      self.skipTest("params lib not built (scons -j1 openpilot/common/libparams_c.so)")

  def _isolated(self):
    import tempfile
    from openpilot.common.params import Params
    d = tempfile.mkdtemp()
    self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
    return d, Params(d)

  def test_key_is_declared_int(self):
    from openpilot.common.params import ParamKeyType
    _, p = self._isolated()
    self.assertEqual(p.get_type("ShowRadarInfo"), ParamKeyType.INT)

  def test_every_level_writes_and_reads_back(self):
    import time
    from openpilot.common.params import Params
    d, p = self._isolated()
    for level in range(4):
      # this line is the regression: on a BOOL key put_int() raises TypeError and
      # nothing is written, so levels 2 and 3 would silently never exist
      p.put_int("ShowRadarInfo", level)
      # a fresh handle reads the store rather than this instance's cached view.
      # The store's reload is mtime-based, so poll instead of assuming a write is
      # visible on the very next read.
      deadline = time.monotonic() + 2.0
      while True:
        got = Params(d).get_int("ShowRadarInfo")
        if got == level or time.monotonic() >= deadline:
          break
        time.sleep(0.02)
      self.assertEqual(got, level)
