import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openpilot.sunnypilot.carrot.signal_display import SignalDisplayReader, publish_display, visible_tracks, project_box


def record():
  return {'version': 1, 'stream': 'road', 'size': [1344, 760], 'frame_id': 20, 'timestamp': 10., 'session': 'worker',
              'tracks': [{'id': 3, 'box': [600, 200, 640, 215], 'state': 'red', 'raw': 'red', 'age': 0.}]}


CAMERA = (22, 10.1, 1344, 760, False)


class TestSignalDisplay(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="signal_display_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)

  def test_red_green_unknown_are_observations_not_permissions(self):
    r = record()
    self.assertEqual(visible_tracks(r, 10.2, CAMERA)[0]['state'], 'red')
    r['tracks'][0].update(raw='green', state='green')
    self.assertEqual(visible_tracks(r, 10.2, CAMERA)[0]['state'], 'green')
    r['tracks'][0]['raw'] = 'unknown'
    self.assertEqual(visible_tracks(r, 10.2, CAMERA)[0]['state'], 'unknown')

  def test_green_first_candidate_is_visible_without_claiming_confirmation(self):
    r = record()
    r['tracks'][0].update(raw='green', state='unknown')
    track = visible_tracks(r, 10.2, CAMERA)[0]
    self.assertEqual(track['state'], 'green')
    self.assertFalse(track['confirmed'])
    r['tracks'][0]['state'] = 'red'
    self.assertFalse(visible_tracks(r, 10.2, CAMERA)[0]['confirmed'])
    r['tracks'][0]['state'] = 'green'
    self.assertTrue(visible_tracks(r, 10.2, CAMERA)[0]['confirmed'])

  def test_remembered_green_does_not_override_missing_or_red_current_evidence(self):
    r = record()
    r['tracks'][0].update(raw='unknown', state='green')
    self.assertEqual(visible_tracks(r, 10.2, CAMERA)[0]['state'], 'unknown')
    r['tracks'][0]['raw'] = 'red'
    track = visible_tracks(r, 10.2, CAMERA)[0]
    self.assertEqual(track['state'], 'red')
    self.assertFalse(track['confirmed'])

  def test_stale_wrong_camera_or_invalid_records_are_hidden(self):
    for change in [{'timestamp': 9.8}, {'timestamp': 11}, {'timestamp': float('nan')},
                   {'stream': 'wide'}, {'size': [1928, 1208]}, {'frame_id': 5},
                   {'version': 2}, {'tracks': None}, {'session': None}]:
      with self.subTest(change=change):
        r = record()
        r.update(change)
        self.assertEqual(visible_tracks(r, 10.2, CAMERA), ())

  def test_wrong_or_stale_displayed_image_hides_boxes(self):
    for camera in [None, (22, 9.8, 1344, 760, False), (22, 11., 1344, 760, False),
                   (22, 10.1, 1344, 760, True), (22, 10.1, 1928, 1208, False)]:
      with self.subTest(camera=camera):
        self.assertEqual(visible_tracks(record(), 10.2, camera), ())

  def test_lost_invalid_or_out_of_frame_boxes_are_hidden(self):
    for change in [{'age': .05}, {'box': [-1, 0, 30, 10]}, {'box': [0, 0, 10, 800]},
                   {'box': [2, 0, 1, 10]}, {'box': [0, 0, float('nan'), 10]}, {'id': 'oops'}]:
      with self.subTest(change=change):
        r = record()
        r['tracks'][0].update(change)
        self.assertEqual(visible_tracks(r, 10.2, CAMERA), ())

  def test_mapping_uses_actual_camera_rectangle_with_crop_offsets(self):
    self.assertEqual(project_box([0, 0, 1344, 760], (-50, -20, 672, 380)), (-50, -20, 672, 380))
    self.assertEqual(project_box([672, 380, 1344, 760], (-50, -20, 672, 380)), (286, 170, 336, 190))

  def test_reader_expires_even_when_file_does_not_change_and_handles_invalid_data(self):
    flag, path = self.tmp_path / 'display_enabled', self.tmp_path / 'display.json'
    path.write_text(json.dumps(record()))
    reader = SignalDisplayReader(flag, path)
    self.assertEqual(reader.read(CAMERA, 10.2), ())
    self.assertFalse(reader.enabled)
    flag.write_text('1')
    reader = SignalDisplayReader(flag, path)
    self.assertEqual(len(reader.read(CAMERA, 10.2)), 1)
    self.assertEqual(reader.read(CAMERA, 10.4), ())
    for bad in ['x' * 9000, '[]', 'null', '{']:
      path.write_text(bad)
      reader.next_read = 0
      self.assertEqual(reader.read(CAMERA, 10.2), ())
    flag.write_text('0')
    self.assertEqual(reader.read(CAMERA, 11.), ())
    self.assertFalse(reader.enabled)

  def test_display_has_separate_endpoint_and_no_control_fields(self):
    r = record()
    t = r['tracks'][0]
    source = {'tracks': [dict(t, evidence={'raw': 'red'})], 'frame_id': 20, 'timestamp_eof': 10_000_000_000,
                  'session': 'worker', 'revalidated': True, 'daytime_comparison': True}
    path = self.tmp_path / 'display.json'
    publish_display(source, path=path)
    out = json.loads(path.read_text())
    self.assertEqual(out['engine'], 'trial')
    self.assertEqual(len(visible_tracks(out, 10.2, CAMERA)), 1)
    self.assertFalse(any(k in out for k in ['hold', 'red_sign', 'released', 'control_permission']))
    self.assertFalse((self.tmp_path / 'carrot_signal_observation.json').exists())

  def test_renderer_status_is_bounded_and_display_only(self):
    reader = SignalDisplayReader(self.tmp_path / 'flag', self.tmp_path / 'data')
    path = self.tmp_path / 'status'
    reader.record_draw(CAMERA, 2, path=path, now=10.)
    self.assertFalse(path.exists())
    reader.enabled = True
    reader.record = record()
    reader.record_draw(CAMERA, 2, path=path, now=10.)
    before = path.read_bytes()
    reader.record_draw(CAMERA, 0, path=path, now=10.1)
    self.assertEqual(path.read_bytes(), before)
    reader.record_draw(CAMERA, 0, path=path, now=11.)
    self.assertEqual(json.loads(path.read_text())['boxes_drawn'], 0)


if __name__ == "__main__":
  unittest.main()
