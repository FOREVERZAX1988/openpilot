#!/usr/bin/env python3
"""Carrot-style shared CPU map renderer; model, Web and USB reuse the same image.

Ported from cp selfdrive/navigation/mapsd.py, keeping this fork's MapsD class
interface and renderer API. cp mechanisms carried over: demand gating,
adaptive render_interval, the 0.5 s render timeout, the 30 s retry backoff,
the Mapbox/PMTiles archive switch and RuntimeDiagnostics.

cp mechanisms NOT carried over (sp capabilities differ, see port report):
  - jetlink_map_demand and ClusterHudScreenMode == 7 demand sources
    (no jetlink service here; ClusterHudScreenMode is a BOOL param in sp).
  - navRoute.carrotRouteId heartbeat (sp's NavRoute has no such field; the
    route is deduplicated by geometry comparison instead).
  - navInstructionCarrot freshness gate uses the stock navInstruction here.
The whole-route prefetch TODO (old mapsd.py:43) is resolved cp-style: only
the current view's tiles are fetched during each render.
"""
import os
import time

import numpy as np

import openpilot.cereal.messaging as messaging
from msgq.visionipc import VisionIpcServer
from openpilot.cereal.visionipc import VisionStreamType
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.runtime_diagnostics import RuntimeDiagnostics
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.navigation.helpers import latest_gps_source
from openpilot.selfdrive.navigation.mapbox_tiles import MapboxTiles
from openpilot.selfdrive.navigation.pmtiles import PMTiles
from openpilot.selfdrive.navigation.preview import WEB_DEMAND_PATH, preview_fresh, write_preview
from openpilot.selfdrive.navigation.renderer import SIZE, MapRenderer
from openpilot.selfdrive.navigation.route import RouteTracker
from openpilot.selfdrive.navigation.tiles import RemoteTiles

ARCHIVE_MAX_AGE = 3600.  # s; a stale Mapbox session is refreshed like cp's


def render_interval(cpu_seconds):
  # At most 10 Hz / approximately 10% of one CPU. A >40 ms render can cause
  # the model's unchanged 500 ms freshness gate to reject the map.
  return max(.1, cpu_seconds * 10)


def map_demand(params, now):
  """Whether anything outside the onroad UI wants the map rendered.

  cp also checks jetlink demand and ClusterHudScreenMode == 7; neither
  capability exists in this fork (no jetlink service; the param is BOOL).
  """
  del now
  return params.get_bool('UsbGpuActive') or preview_fresh(WEB_DEMAND_PATH)


class MapsD:
  def __init__(self, params=None, diagnostics=None):
    self.params = params if params is not None else Params()
    self.renderer = None
    self.tracker = None
    self.route = np.empty((0, 2))
    self.retry_at = 0.0
    self.next_render = 0.0
    self.next_preview = 0.0
    self.demand_checked = 0.0
    self.demand = False
    self.was_ready = False
    self.mapbox_token = ''
    self.archive_created = 0.
    self.frame = np.zeros((SIZE, SIZE), dtype=np.uint8)  # last published frame, replayed between renders
    self.timestamp = 0
    self.diagnostics = diagnostics if diagnostics is not None else RuntimeDiagnostics('mapsd', cloudlog.event, interval=5.)

  def update(self, sm) -> tuple[np.ndarray, int]:
    """The map frame for the latest messages: black with a zero timestamp without a usable map, never stale."""
    if sm.updated['navRoute']:
      route = np.array([(c.longitude, c.latitude) for c in sm['navRoute'].coordinates], dtype=np.float64).reshape((-1, 2))
      if not np.array_equal(route, self.route):  # cp deduplicates by carrotRouteId; sp's NavRoute has none
        self.route = route
        self.tracker = RouteTracker(route) if 2 <= len(route) <= 4096 and np.isfinite(route).all() else None  # progress along the route starts over
        self.next_render = 0.
    now = time.monotonic()
    source = latest_gps_source(sm)
    gps = sm[source] if source is not None else None
    if now >= self.demand_checked:
      self.demand = map_demand(self.params, now)
      token = os.environ.get('MAPBOX_TOKEN') or self.params.get('MapboxPublicKey') or ''
      if isinstance(token, bytes):
        token = token.decode('utf-8')
      if token != self.mapbox_token or (self.renderer is not None and now - self.archive_created >= ARCHIVE_MAX_AGE):
        self.close()
        self.retry_at = self.next_render = 0.
        self.mapbox_token = token
      self.demand_checked = now + 1.
    fresh_tbt = sm.valid.get('navInstruction', False) and 0 <= now - sm.recv_time['navInstruction'] < 2.
    ready = self.demand and self.tracker is not None and gps is not None and fresh_tbt
    # Between renders the last frame is replayed unchanged (same timestamp), so the
    # consumer's freshness gate keeps passing; a lost route/fix publishes black instead.
    if now < self.next_render and not (self.was_ready and not ready):
      return self.frame, self.timestamp
    started, cpu_started = time.monotonic(), time.process_time()
    image = np.zeros((SIZE, SIZE), dtype=np.uint8)
    valid = False
    reason = 'idle' if not self.demand else 'route' if self.tracker is None else 'position' if gps is None else 'instruction' if not fresh_tbt else 'tiles'
    try:
      if ready and now >= self.retry_at:
        if self.renderer is None:
          archive = MapboxTiles(self.mapbox_token) if self.mapbox_token else PMTiles(RemoteTiles())
          self.archive_created = now
          self.renderer = MapRenderer(archive)
        # Fetch only the current view; do not prefetch a whole route (resolves the old prefetch TODO cp-style).
        pose = self.tracker.snap(gps.longitude, gps.latitude)
        image, valid = self.renderer.render(*pose, self.route)
        reason = 'ready' if valid else 'tiles'
    except (OSError, ValueError, RuntimeError):
      cloudlog.warning('mapsd: map unavailable; retry in 30 seconds')
      self.close()  # a changed archive needs a fresh reader
      self.retry_at = time.monotonic() + 30.
    finished = time.monotonic()
    if finished - started >= .5:
      image.fill(0)
      valid = False
      reason = 'slow'
    cpu = time.process_time() - cpu_started
    self.next_render = finished + (render_interval(cpu) if valid else max(1., render_interval(cpu)))
    self.diagnostics.record(render_ms=(finished - started) * 1000, cpu_ms=cpu * 1000,
                            context={'map_valid': valid, 'route_points': len(self.route),
                                     'interval': render_interval(cpu), 'reason': reason})
    if valid:
      self.frame, self.timestamp = image, sm.logMonoTime[source]
    else:
      self.frame, self.timestamp = np.zeros((SIZE, SIZE), dtype=np.uint8), 0
    if finished >= self.next_preview:
      write_preview(self.frame, reason=reason)
      self.next_preview = finished + .5
    self.was_ready = ready
    return self.frame, self.timestamp

  def close(self):
    if self.renderer is not None:
      self.renderer.archive.close()
    self.renderer = None


def main():
  # Auxiliary work shares only the little cores. Never compete at FIFO priority
  # with camera/control, radar, driving model or DM on cores 4..7.
  if hasattr(os, 'sched_setaffinity'):
    os.sched_setscheduler(0, os.SCHED_OTHER, os.sched_param(0))
    allowed = os.sched_getaffinity(0) & {0, 1, 2, 3}
    if allowed:
      os.sched_setaffinity(0, allowed)
    os.nice(15)
  rk = Ratekeeper(10., print_delay_threshold=None)
  sm = messaging.SubMaster(['gpsLocation', 'gpsLocationExternal', 'navRoute', 'navInstruction'])
  server = VisionIpcServer('mapsd')
  server.create_buffers_with_sizes(VisionStreamType.VISION_STREAM_MAP, 4, SIZE, SIZE, SIZE * SIZE, SIZE, SIZE * SIZE)
  server.start_listener()
  mapsd = MapsD()
  try:
    while True:
      sm.update(0)
      image, timestamp = mapsd.update(sm)
      server.send(VisionStreamType.VISION_STREAM_MAP, image.tobytes(), rk.frame, timestamp, time.monotonic_ns())
      rk.keep_time()
  finally:
    mapsd.close()


if __name__ == '__main__':
  main()
