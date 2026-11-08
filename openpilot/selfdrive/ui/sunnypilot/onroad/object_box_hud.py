"""General object boxes on the road view (display only).

The xiaoge YOLOv8n head (v_asm_server) publishes a ``xiaogeVision`` document on
customReservedRawData0 carrying normalised centre/size boxes, COCO class ids,
confidence and a monocular distance. Nothing on the car screen consumed that
``yolo`` section: only the traffic-light HUD (signal_hud.py) drew boxes, so
pedestrians, motorcycles and adjacent-lane cars stayed invisible while driving
even though the detector was running.

Opt-in and inert by default: the head emits ``yolo`` only while
YoloObstacleEnabled == 1, so with the shipped default (0) this draws nothing and
costs one idle subscription.

Every failure path degrades to "draw nothing". A render pass must never raise:
the 2026-11-08 zh-CHS dev-UI KeyError turned one bad dict lookup into a UI
restart loop.
"""
import json
import time

import raylib_nb as rl

import openpilot.cereal.messaging as messaging
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

SERVICE = "customReservedRawData0"
DOC_TYPE = "xiaogeVision"

# COCO ids kept by yolo_inference.KEEP_CLASSES that are road users. Traffic
# lights have their own HUD and stop signs are static, so both stay out.
OBJECT_CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
CLASS_LABELS = {
  "person": "行人",
  "bicycle": "自行车",
  "car": "车辆",
  "motorcycle": "摩托车",
  "bus": "公交",
  "truck": "卡车",
}

BOX_COLOR = rl.Color(255, 205, 40, 255)  # the yellow the driver expects
BOX_STROKE = 3
BOX_ROUNDNESS = 0.2
LABEL_SIZE = 24
LABEL_GAP = 4
MAX_AGE_S = 1.2          # the head runs 3-6 Hz and pauses when parked
MAX_BOXES = 16
READ_INTERVAL_S = 0.2    # 5 Hz is plenty for a 3-6 Hz producer
FRAME_W, FRAME_H = 1928, 1208  # yolo_inference.DEFAULT_WIDTH_PX / _HEIGHT_PX


def parse_yolo_dets(raw: bytes) -> tuple[list[dict], int]:
  """Return (road-user detections, producer mono time); empty on any surprise."""
  try:
    doc = json.loads(raw)
    if doc.get("type") != DOC_TYPE:
      return [], 0
    yolo = doc.get("yolo") or {}
    dets = [d for d in (yolo.get("dets") or [])
            if isinstance(d, dict) and d.get("cid") in OBJECT_CLASSES]
    return dets, int(yolo.get("receivedMonoTimeNanos") or 0)
  except (ValueError, TypeError, AttributeError):
    return [], 0


def box_to_screen(det: dict, rect: rl.Rectangle) -> rl.Rectangle | None:
  """Map a normalised centre/size box onto the camera preview rect.

  Same aspect-preserving cover fit the camera view uses, so a box lands where
  the driver actually sees the object.
  """
  try:
    cx, cy = float(det["cx"]), float(det["cy"])
    w, h = float(det["w"]), float(det["h"])
  except (KeyError, TypeError, ValueError):
    return None
  if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0) or rect.height <= 0 or rect.width <= 0:
    return None

  frame_ar = FRAME_W / FRAME_H
  widget_ar = rect.width / rect.height
  zx = min(frame_ar / widget_ar, 1.0)
  zy = min(widget_ar / frame_ar, 1.0)
  scale_x, scale_y = rect.width * zx, rect.height * zy
  x_off = rect.x + (rect.width - scale_x) / 2
  y_off = rect.y + (rect.height - scale_y) / 2
  return rl.Rectangle(x_off + (cx - w / 2) * scale_x, y_off + (cy - h / 2) * scale_y,
                      w * scale_x, h * scale_y)


class ObjectBoxRenderer:
  """Draws the detector's tracked road users over the camera preview."""

  def __init__(self):
    self._font = gui_app.font(FontWeight.SEMI_BOLD)
    # Its own subscriber: ui_state's SubMaster feeds all_alive(), and a 0 Hz
    # raw-data channel must not join that set.
    self._sm = messaging.SubMaster([SERVICE], ignore_alive=[SERVICE], ignore_valid=[SERVICE])
    self._dets: list[dict] = []
    self._frame_ns = 0
    self._next_read = 0.0
    self._shadow = rl.Color(0, 0, 0, 140)
    self._backdrop = rl.Color(0, 0, 0, 120)

  def _refresh(self, now: float) -> None:
    if now < self._next_read:
      return
    self._next_read = now + READ_INTERVAL_S
    try:
      # SubMaster.update() defaults to a 100 ms poll timeout. This runs on the
      # UI render thread and customReservedRawData0 is a 0 Hz channel while the
      # xiaoge vision server is off, so the default blocked every 0.2 s read for
      # a full 100 ms: measured 22/50/155 ms frame cycle (13 fps, visible camera
      # judder). update(0) is non-blocking; a missed frame is fine at 5 Hz.
      self._sm.update(0)
      if not self._sm.updated[SERVICE]:
        return
      self._dets, self._frame_ns = parse_yolo_dets(bytes(self._sm[SERVICE].customReservedRawData0))
    except Exception:
      self._dets, self._frame_ns = [], 0

  def render(self, rect: rl.Rectangle) -> None:
    now = time.monotonic()
    self._refresh(now)
    if not self._dets or not self._frame_ns:
      return
    age = (time.monotonic_ns() - self._frame_ns) / 1e9
    if not (0.0 <= age <= MAX_AGE_S):
      return

    for det in self._dets[:MAX_BOXES]:
      srect = box_to_screen(det, rect)
      if srect is None or srect.width < 2 or srect.height < 2:
        continue
      rl.draw_rectangle_rounded_lines_ex(
        rl.Rectangle(srect.x - 1, srect.y - 1, srect.width + 2, srect.height + 2),
        BOX_ROUNDNESS, 6, BOX_STROKE + 2, self._shadow)
      rl.draw_rectangle_rounded_lines_ex(srect, BOX_ROUNDNESS, 6, BOX_STROKE, BOX_COLOR)

      label = tr(CLASS_LABELS[OBJECT_CLASSES[det["cid"]]])
      text_size = measure_text_cached(self._font, label, LABEL_SIZE)
      lx = srect.x + srect.width / 2 - text_size.x / 2
      ly = srect.y - text_size.y - LABEL_GAP
      if ly < rect.y:
        ly = srect.y + srect.height + LABEL_GAP
      backdrop = rl.Rectangle(lx - 6, ly - 2, text_size.x + 12, text_size.y + 4)
      rl.draw_rectangle_rounded(backdrop, 0.4, 8, self._backdrop)
      rl.draw_text_ex(self._font, label, rl.Vector2(lx, ly), LABEL_SIZE, 0, BOX_COLOR)
