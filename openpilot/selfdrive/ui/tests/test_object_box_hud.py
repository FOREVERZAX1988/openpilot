"""Contract tests for the general object-box overlay.

The overlay is display-only and opt-in (YoloObstacleEnabled). What must hold is
that a malformed or unrelated payload can never raise inside a render pass --
the 2026-11-08 zh-CHS dev-UI KeyError turned exactly that into a UI restart
loop.
"""
import json
import unittest

import raylib_nb as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.object_box_hud import (
  OBJECT_CLASSES, box_to_screen, parse_yolo_dets,
)


def document(dets, *, doc_type="xiaogeVision", ns=1_000):
  return json.dumps({
    "type": doc_type,
    "version": 1,
    "yolo": {"valid": True, "receivedMonoTimeNanos": ns, "dets": dets},
  }).encode()


class TestParseYoloDets(unittest.TestCase):
  def test_keeps_road_users_only(self):
    dets = [
      {"cid": 0, "cx": .5, "cy": .5, "w": .1, "h": .2},   # person
      {"cid": 3, "cx": .2, "cy": .5, "w": .05, "h": .1},  # motorcycle
      {"cid": 9, "cx": .1, "cy": .1, "w": .1, "h": .1},   # traffic light -> own HUD
      {"cid": 11, "cx": .1, "cy": .1, "w": .1, "h": .1},  # stop sign -> static
      {"cid": 99, "cx": .1, "cy": .1, "w": .1, "h": .1},
    ]
    dets_out, ns = parse_yolo_dets(document(dets))
    self.assertEqual([d["cid"] for d in dets_out], [0, 3])
    self.assertEqual(ns, 1_000)

  def test_ignores_unrelated_documents(self):
    out, ns = parse_yolo_dets(document([{"cid": 0, "cx": .5, "cy": .5, "w": .1, "h": .1}],
                                       doc_type="somethingElse"))
    self.assertEqual((out, ns), ([], 0))

  def test_missing_yolo_section(self):
    out, ns = parse_yolo_dets(json.dumps({"type": "xiaogeVision"}).encode())
    self.assertEqual((out, ns), ([], 0))

  def test_malformed_payload_degrades_to_empty(self):
    for raw in (b"", b"{", b"null", b"[]", b'"x"', b"123"):
      with self.subTest(raw=raw):
        self.assertEqual(parse_yolo_dets(raw), ([], 0))

  def test_non_dict_entries_are_dropped(self):
    out, _ = parse_yolo_dets(document([{"cid": 0, "cx": .5, "cy": .5, "w": .1, "h": .1},
                                       "junk", 7, None]))
    self.assertEqual(len(out), 1)


class TestBoxToScreen(unittest.TestCase):
  def test_centre_box_maps_to_rect_centre(self):
    rect = rl.Rectangle(100, 50, 800, 600)
    srect = box_to_screen({"cx": .5, "cy": .5, "w": .2, "h": .2}, rect)
    self.assertIsNotNone(srect)
    self.assertAlmostEqual(srect.x + srect.width / 2, rect.x + rect.width / 2, delta=1.0)
    self.assertAlmostEqual(srect.y + srect.height / 2, rect.y + rect.height / 2, delta=1.0)
    self.assertGreater(srect.width, 0)
    self.assertGreater(srect.height, 0)

  def test_rejects_invalid_boxes(self):
    rect = rl.Rectangle(0, 0, 800, 600)
    cases = (
      {},
      {"cx": .5},
      {"cx": .5, "cy": .5, "w": 0.0, "h": .1},
      {"cx": .5, "cy": .5, "w": .1, "h": 2.0},
      {"cx": "x", "cy": .5, "w": .1, "h": .1},
    )
    for det in cases:
      with self.subTest(det=det):
        self.assertIsNone(box_to_screen(det, rect))

  def test_zero_sized_rect_is_safe(self):
    self.assertIsNone(box_to_screen({"cx": .5, "cy": .5, "w": .1, "h": .1},
                                    rl.Rectangle(0, 0, 0, 0)))


class TestClassTable(unittest.TestCase):
  def test_table_matches_detector_keep_list(self):
    # yolo_inference.KEEP_CLASSES road users; traffic light / stop sign excluded.
    self.assertEqual(set(OBJECT_CLASSES), {0, 1, 2, 3, 5, 7})


if __name__ == "__main__":
  unittest.main()
