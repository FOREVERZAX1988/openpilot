"""Nonblocking model map input. Unsupported driving models do no map work.

Ported from carrot (selfdrive/navigation/map_client.py): one copy of the
code adapted to sp's service names. Two changes from cp:
  - cp subscribes ``navInstructionCarrot``; sp's guidance is published as
    ``navInstructionCarrotSP`` (same Maneuver list shape).
  - cp gates on ``model.views``; sp model states expose their scalar input
    slots as ``numpy_inputs`` (modeld_v2) or ``npy`` (stock modeld).
Everything else, including the degradation gate, is byte-for-byte cp's.
"""
import time

import numpy as np

from openpilot.selfdrive.navigation.helpers import navigation_input


def model_input_views(model):
  views = getattr(model, 'numpy_inputs', None)
  if views is None:
    views = getattr(model, 'npy', None)
  return views if views is not None else {}


class MapInput:
  def __init__(self):
    self.client = None
    self.retry_at = 0.
    self.image = None
    self.image_time = 0.
    self.image_time_ns = 0
    self.route_time = 0

  def update(self, model, sm, speed):
    views = model_input_views(model)
    if 'nav_map' not in views or 'navigation' not in views:
      self.image = None
      return {}
    note_map = getattr(model, "set_nav_metadata", None)
    if note_map is not None:
      note_map(None)
    now = time.monotonic()
    if self.client is None:
      from msgq.visionipc import VisionIpcClient, VisionStreamType
      self.client = VisionIpcClient('mapsd', VisionStreamType.VISION_STREAM_MAP, True)
    if not self.client.is_connected() and now >= self.retry_at:
      self.client.connect(False)
      self.retry_at = now + 1.
    if self.client.is_connected():
      buf = self.client.recv(0)
      if buf is not None:
        self.image = None
        if (buf.width, buf.height) == (256, 256) and len(buf.data) >= 65536:
          self.image = np.frombuffer(buf.data, np.uint8, count=65536).reshape(256, 256).copy()
          self.image_time_ns = int(self.client.timestamp_eof)
          self.image_time = self.image_time_ns * 1e-9
          self.route_time = self.client.timestamp_sof
    result = {}
    if sm.valid['navInstructionCarrotSP'] and 0 <= now - sm.recv_time['navInstructionCarrotSP'] < 2:
      result['navigation'] = navigation_input(sm['navInstructionCarrotSP'].allManeuvers,
                                             max(0., speed) * (now - sm.recv_time['navInstructionCarrotSP']))
      if (self.image is not None and 0 <= now - self.image_time < .5
          and self.route_time != 0 and self.route_time == sm['navRoute'].carrotRouteId and sm.valid['navRoute']):
        result['nav_map'] = self.image
        if note_map is not None:
          note_map((int(self.route_time), self.image_time_ns,
                    min(self.image_time_ns + 500_000_000, int((sm.recv_time['navInstructionCarrotSP'] + 2.) * 1e9))))
    return result
