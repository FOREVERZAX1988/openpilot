"""行车预览里那条 path 的「补足到最小绘制距离」：纯几何冒烟。

背景（2026-10-24 驾驶者报告）：停车预览里 path 画不出来。量过才发现它**一直在画**，
只是 parking 时模型的 plan 只推 6.0 m（vEgo=0），而路视图 zoom 1.1 下画面底边对应
地面约 6.2 m —— 6 m 以内的地面全在框外，33 个点投影到 y=1092..1435（可视 y 30..1050），
整条在屏幕下沿之外。所以这不是合并丢件，是预览特有几何：

    model_renderer.py: MIN_DRAW_DISTANCE(10 m) 只被当成 max_distance 的上限用，
    而 `_map_line_to_polygon` 的插值分支要求 0 < max_idx < len-1 —— plan 比 10 m
    还短时 max_idx == len-1，插值永远不触发，线就停在 6 m。

修法：preview 里把折线沿**自己最后一段的切线**补一个点到 max_distance。模型自己给出的
点一个不动（plan 的形状不被篡改），只把线延伸到能进画面的距离；onroad 完全不进这条分支。

本文件只跑数学（不打桩 pyray 绘制、不开窗口），钉住：

  1. 短 horizon -> 补一个点，正好落在 max_distance 上，原点逐字节不变；
  2. 补出来的点在这条折线的延长线上（切线方向、横向偏移都保真，不强行掰直）；
  3. horizon 已经 >= max_distance -> 原样返回，一个点都不动（onroad 行为不变）；
  4. 退化输入（单点、x 方向不前进）-> 原样返回，不抛异常；
  5. dtype 保持（float32 进、float32 出，喂给 shader 的那份不能悄悄变 float64）。

Run from the repo root (no display):

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/model_path_extend_smoke.py

Exit status is 0 when every check passes. 文件名刻意不用 test_*.py：它要 import
model_renderer，会连带 import pyray / ui_state，避免污染 pytest 共享会话
（同 preview_row_layout_smoke.py / hud_row_layout_smoke.py 的约定）。
"""

from __future__ import annotations

import sys


class _Tex:
  width, height, id = 100, 100, 1


class _Font:
  baseSize = 48
  texture = _Tex()


from openpilot.system.ui.lib.application import gui_app

gui_app.font = lambda *a, **k: _Font()
gui_app.texture = lambda *a, **k: _Tex()

import numpy as np

from openpilot.selfdrive.ui.onroad.model_renderer import (
  MAX_DRAW_DISTANCE, MIN_DRAW_DISTANCE, extend_polyline,
)

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
  if cond:
    print(f"  ok   {name}")
  else:
    FAILS.append(f"{name}: {detail}")
    print(f"  FAIL {name}: {detail}")


def parked_path() -> np.ndarray:
  """停在原地时模型真的给的东西（2026-10-24 设备实测那一帧的取值）。"""
  x = np.linspace(0.0, 6.01, 33, dtype=np.float32)
  y = np.linspace(0.0, 0.058, 33, dtype=np.float32)
  z = np.linspace(0.0, 0.031, 33, dtype=np.float32)
  return np.stack([x, y, z], axis=1).astype(np.float32)


def main() -> int:
  print("1. 短 horizon 补到 MIN_DRAW_DISTANCE")
  pts = parked_path()
  out = extend_polyline(pts, MIN_DRAW_DISTANCE)
  check("补了一个点", out.shape[0] == pts.shape[0] + 1, f"{out.shape}")
  check("原点逐字节不变", np.array_equal(out[:pts.shape[0]], pts))
  check("末点 x == max_distance", abs(float(out[-1, 0]) - MIN_DRAW_DISTANCE) < 1e-5, f"{out[-1, 0]}")
  check("dtype 保持 float32", out.dtype == np.float32, str(out.dtype))

  print("2. 补出来的点在延长线上（切线保真）")
  # 一条向右前方弯的线：最后一段的方向不能被掰成"正前方"
  xs = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
  ys = np.array([0.0, 0.2, 0.5, 0.9], dtype=np.float32)
  zs = np.zeros_like(xs)
  bent = np.stack([xs, ys, zs], axis=1)
  out = extend_polyline(bent, 10.0)
  d_last = bent[-1] - bent[-2]
  d_new = out[-1] - out[-2]
  check("方向与最后一段平行", np.allclose(d_new / np.linalg.norm(d_new), d_last / np.linalg.norm(d_last), atol=1e-5),
        f"{d_new} vs {d_last}")
  check("补点在线段延长线上", np.allclose(out[-1], bent[-1] + d_last / d_last[0] * (10.0 - bent[-1][0]), atol=1e-5),
        f"{out[-1]}")

  print("3. horizon 已够长 -> 原样返回")
  long_path = np.stack([np.linspace(0.0, 60.0, 33, dtype=np.float32),
                        np.zeros(33, dtype=np.float32), np.zeros(33, dtype=np.float32)], axis=1)
  check("一个点都不动", extend_polyline(long_path, MIN_DRAW_DISTANCE) is long_path)
  # 渲染器给 path 的 max_distance 是 clip(path_x[-1], 10, 100)，所以 horizon 长于 100 m
  # 时同样一个点都不动（onroad 正常行驶就是这个状态）
  past_max = np.stack([np.linspace(0.0, 150.0, 33, dtype=np.float32),
                       np.zeros(33, dtype=np.float32), np.zeros(33, dtype=np.float32)], axis=1)
  check("超过 MAX_DRAW_DISTANCE 同样不动", extend_polyline(past_max, MAX_DRAW_DISTANCE) is past_max)

  print("4. 退化输入")
  one = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)
  check("单点原样返回", extend_polyline(one, 10.0) is one)
  sideways = np.array([[5.0, 0.0, 0.0], [5.0, 1.0, 0.0]], dtype=np.float32)
  check("x 方向不前进时原样返回", extend_polyline(sideways, 10.0) is sideways)
  empty = np.empty((0, 3), dtype=np.float32)
  check("空数组原样返回", extend_polyline(empty, 10.0) is empty)

  print()
  if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
      print("  -", f)
    return 1
  print("all model-path-extend checks passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
