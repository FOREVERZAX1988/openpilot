"""无头几何冒烟：onroad 顶部左侧一行「设定速度胶囊 vs 限速标志」不得重叠。

背景（2026-10-04 实车 bug）：限速标志按 `CarrotPanelSide == 0`（"左"）被画在
`rect.x + 60` —— 正是设定速度胶囊自己的槽位（胶囊 x = rect.x + 46、宽 200、高 204），
实车表现为限速圆圈压在 MAX/设定速度胶囊上（用户报告"限速标识跟设定巡航速度标识重叠"）。

本测试驱动**真实渲染器**（`HudRendererSP` + `SpeedLimitRenderer`），把 pyray 的绘制函数
换成记录器取回真实矩形（不初始化窗口/GL，纯 CPU 几何），断言：

  1. 公制/英制下，限速标志左缘 ≥ 胶囊右缘（含安全间隙）；
  2. 坐标与上游 sunnypilot 原式逐像素一致（防未来静默移位）；
  3. 旧口径（`rect.x + 60`）在同 rect 下确实与胶囊相交 —— 作为 bug 见证。

Run from the repo root (no display):

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/hud_row_layout_smoke.py

Exit status is 0 when every check passes. 文件名刻意不用 test_*.py：它会打桩 pyray 与
ui_state，避免污染 pytest 共享会话（同 cluster_overlay_smoke.py 的约定）。
"""

from __future__ import annotations

import sys
import types

# ---------------------------------------------------------------------------
# 打桩：gui_app 字体/纹理（构造渲染器需要，不触发 GL）
# ---------------------------------------------------------------------------


class _Tex:
  width, height, id = 100, 100, 1


class _Font:
  baseSize = 48
  texture = _Tex()


from openpilot.system.ui.lib.application import gui_app  # noqa: E402

gui_app.font = lambda *a, **k: _Font()
gui_app.texture = lambda *a, **k: _Tex()

import openpilot.selfdrive.ui.sunnypilot.onroad.speed_limit as sl  # noqa: E402
import openpilot.selfdrive.ui.sunnypilot.onroad.hud_renderer as hsp  # noqa: E402
from openpilot.selfdrive.ui.onroad.hud_renderer import UI_CONFIG  # noqa: E402
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus  # noqa: E402
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode as SpeedLimitMode  # noqa: E402

# 文本测量走真实字体文件，无头环境不需要 —— 直接给常量宽度。
_VEC = types.SimpleNamespace(x=0.0, y=0.0)
for _mod in (sl, hsp):
  _mod.measure_text_cached = lambda *a, **k: _VEC

# ---------------------------------------------------------------------------
# 记录 pyray 绘制调用（几何取回）
# ---------------------------------------------------------------------------

DRAWN: list[tuple] = []

import pyray as rl  # noqa: E402

rl.draw_rectangle_rounded = lambda rect, *a, **k: DRAWN.append(("rounded", (rect.x, rect.y, rect.width, rect.height)))
rl.draw_rectangle_rounded_lines_ex = lambda *a, **k: None
rl.draw_circle_v = lambda center, radius, color: DRAWN.append(("circle", center.x, center.y, radius))
rl.draw_ring = lambda *a, **k: None
rl.draw_text_ex = lambda *a, **k: None

# ---------------------------------------------------------------------------
# 假 sm / 状态
# ---------------------------------------------------------------------------


def _ns(**kw):
  return types.SimpleNamespace(**kw)


def install_state(metric: bool) -> None:
  ui_state.sm = {
    "longitudinalPlanSP": _ns(speedLimit=_ns(assist=_ns(active=False))),
    "carControl": _ns(cruiseControl=_ns(override=False), enabled=False),
    "carState": _ns(cruiseState=_ns(speedCluster=0.0)),
  }
  ui_state.is_metric = metric
  ui_state.status = UIStatus.DISENGAGED
  ui_state.speed_limit_mode = SpeedLimitMode.warning
  ui_state.started_frame = 0
  ui_state.CP_SP = _ns(pcmCruiseSpeed=True)


def _pill_rect(hud, rect) -> tuple[float, float, float, float]:
  DRAWN.clear()
  hud._draw_set_speed(rect)
  for k in DRAWN:
    if k[0] == "rounded":
      return k[1]
  raise AssertionError("设定速度胶囊没有绘制")


def _sign_rect(renderer, rect, metric: bool) -> tuple[float, float, float, float]:
  DRAWN.clear()
  renderer._render(rect)
  if metric:  # Vienna（圆形标志）：draw_circle_v 的半径已含外圈
    for k in DRAWN:
      if k[0] == "circle":
        _, cx, cy, r = k
        return (cx - r, cy - r, 2 * r, 2 * r)
  else:  # MUTCD（矩形标志）
    for k in DRAWN:
      if k[0] == "rounded":
        return k[1]
  raise AssertionError("限速标志没有绘制")


def _intersects(a, b) -> bool:
  return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def main() -> int:
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

  rect = rl.Rectangle(0.0, 0.0, 2160.0, 1080.0)
  renderer = sl.SpeedLimitRenderer()
  renderer.speed_limit_valid = True
  renderer.speed_limit_last = 60.0
  renderer.speed_limit_final_last = 60.0
  renderer.speed_limit_offset = 0.0
  renderer.speed_limit_ahead_valid = False
  renderer.speed_limit_source = sl.SpeedLimitSource.none
  renderer.speed_limit_assist_state = sl.AssistState.disabled
  renderer.speed = 0.0
  hud = hsp.HudRendererSP()
  hud.is_cruise_set = True
  hud.set_speed = 100.0

  def no_overlap_metric():
    install_state(True)
    pill = _pill_rect(hud, rect)
    sign = _sign_rect(renderer, rect, True)
    assert pill[0] + pill[2] <= sign[0], f"公制下重叠: 胶囊右缘 {pill[0] + pill[2]} > 标志左缘 {sign[0]}"

  def no_overlap_imperial():
    install_state(False)
    pill = _pill_rect(hud, rect)
    sign = _sign_rect(renderer, rect, False)
    assert pill[0] + pill[2] <= sign[0], f"英制下重叠: 胶囊右缘 {pill[0] + pill[2]} > 标志左缘 {sign[0]}"

  def upstream_geometry_metric():
    install_state(True)
    pill = _pill_rect(hud, rect)
    sign = _sign_rect(renderer, rect, True)
    assert pill == (46.0, 45.0, 200.0, 204.0), f"胶囊几何漂移: {pill}"
    # 上游原式 rect.x + 60 + width + 30 - 6 = 284；圆半径 (200+18)/2 = 109 → 左缘 284-9
    assert sign[0] == 275.0 and sign[2] == 218.0, f"标志几何漂移: {sign}"

  def upstream_geometry_imperial():
    install_state(False)
    pill = _pill_rect(hud, rect)
    sign = _sign_rect(renderer, rect, False)
    assert pill == (60.0, 45.0, 172.0, 204.0), f"胶囊几何漂移: {pill}"
    assert sign == (256.0, 39.0, 172.0, 216.0), f"标志几何漂移: {sign}"

  def both_panel_sides_identical():
    """CarrotPanelSide 取值不再影响限速标志位置（左槽已被胶囊占用）。"""
    install_state(True)
    real_params = ui_state.params
    try:
      ui_state.params = _ns(get=lambda key, *a, **k: 1 if key == "CarrotPanelSide" else 100)
      with_side_1 = _sign_rect(renderer, rect, True)
      ui_state.params = _ns(get=lambda key, *a, **k: 0 if key == "CarrotPanelSide" else 100)
      with_side_0 = _sign_rect(renderer, rect, True)
    finally:
      ui_state.params = real_params
    assert with_side_0 == with_side_1, f"标志位置不应随 CarrotPanelSide 变化: {with_side_0} vs {with_side_1}"

  def legacy_geometry_overlapped():
    """bug 见证：旧口径 x = rect.x + 60 与胶囊相交（说明为何删除该分支）。"""
    install_state(True)
    pill = _pill_rect(hud, rect)
    legacy = (60.0, 39.0, 200.0, 216.0)
    assert _intersects(legacy, pill), "旧口径应重叠（回归见证失效，说明胶囊几何变了）"

  def fix_is_load_bearing():
    """反证：把几何换回旧口径（标志画在 rect.x + 60）时，重叠检查必须报错。"""
    install_state(True)
    original = sl.hud_left_row_rects
    try:
      def legacy(rect, metric):
        pill, _ = original(rect, metric)
        return pill, rl.Rectangle(rect.x + 60, rect.y + 45 - 6, pill.width, UI_CONFIG.set_speed_height + 12)
      sl.hud_left_row_rects = legacy
      try:
        no_overlap_metric()
      except AssertionError:
        return
      raise AssertionError("旧口径下重叠检查竟然通过 —— 用例没锁住 bug")
    finally:
      sl.hud_left_row_rects = original

  check("反证：旧口径几何会被本用例判为重叠", fix_is_load_bearing)
  check("metric: 限速标志不与设定速度胶囊重叠", no_overlap_metric)
  check("imperial: 限速标志不与设定速度胶囊重叠", no_overlap_imperial)
  check("metric: 几何与上游原式逐像素一致", upstream_geometry_metric)
  check("imperial: 几何与上游原式逐像素一致", upstream_geometry_imperial)
  check("CarrotPanelSide 不再移动限速标志", both_panel_sides_identical)
  check("bug 见证：旧口径 rect.x+60 与胶囊相交", legacy_geometry_overlapped)
  def ui_config_constants_pinned():
    got = (UI_CONFIG.set_speed_width_metric, UI_CONFIG.set_speed_width_imperial, UI_CONFIG.set_speed_height)
    assert got == (200, 172, 204), f"UI_CONFIG 常量漂移: {got}"

  check("UI_CONFIG 常量未被改动", ui_config_constants_pinned)

  print(f"\nHUD row layout checks: {checks} checks, {len(failures)} failures")
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
