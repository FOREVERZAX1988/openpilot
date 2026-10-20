"""无头几何冒烟：行车预览的「广角 / 普通 / 退出」三键不得压在底部状态栏文字上。

背景（2026-10-20 用户报告）：点开行车预览后，三个切换摄像头的按钮「位置太低，跟最
底部的状态栏文字重叠」。底部的状态栏是 sunnypilot 的开发者 UI 底栏
（`DevUIInfo` = BOTTOM/BOTH 时画在画面最后 61px：一条半透明黑底 + 一行数值文字
aEgo/前车速度/摩擦/方位/海拔，见 sunnypilot/onroad/developer_ui/__init__.py），
而按钮行原先只留 `PREVIEW_BTN_PAD`(16px) 边距，行底距底边 16px，正好落在这行字上。

本测试只跑几何（不打桩 pyray 绘制、不开窗口），断言：

  1. 三个按钮按屏宽居中、等宽等距、都在内容矩形内；
  2. 开发者 UI 底栏关掉时（reserved = 0）几何与修前逐像素一致 —— 不误伤没开底栏的人；
  3. 底栏打开时（reserved = get_bottom_dev_ui_offset()）按钮行与 61px 底栏不相交，
     且至少留 4px 间隙；
  4. 旧口径（不留 reserved）在同 rect 下确实与底栏相交 —— 作为 bug 见证。

Run from the repo root (no display):

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/preview_row_layout_smoke.py

Exit status is 0 when every check passes. 文件名刻意不用 test_*.py：它会打桩
gui_app 与 ui_state，避免污染 pytest 共享会话（同 hud_row_layout_smoke.py 的约定）。
"""

from __future__ import annotations

import sys


class _Tex:
  width, height, id = 100, 100, 1


class _Font:
  baseSize = 48
  texture = _Tex()


from openpilot.system.ui.lib.application import gui_app  # noqa: E402

gui_app.font = lambda *a, **k: _Font()
gui_app.texture = lambda *a, **k: _Tex()

import pyray as rl  # noqa: E402

from openpilot.selfdrive.ui.onroad.augmented_road_view import (  # noqa: E402
  PREVIEW_BTN_H, PREVIEW_BTN_PAD, PREVIEW_BTN_W, preview_button_rects,
)
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import (  # noqa: E402
  DeveloperUiState, get_bottom_dev_ui_offset,
)
from openpilot.selfdrive.ui.ui_state import ui_state  # noqa: E402

# 开发者 UI 底栏在 developer_ui/__init__.py 里是写死的 61px（黑底 + 一行字）。
DEV_UI_BAR_H = 61
MIN_GAP = 4

# comma 3X（tizi）实际屏：2160x1080，内容矩形扣掉 UI_BORDER_SIZE。
SCREEN = rl.Rectangle(30, 30, 2100, 1020)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
  print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
  if not ok:
    failures.append(name)


def intersects(a: rl.Rectangle, b: rl.Rectangle) -> bool:
  return not (a.x + a.width <= b.x or b.x + b.width <= a.x or
              a.y + a.height <= b.y or b.y + b.height <= a.y)


def dev_bar_rect(rect: rl.Rectangle) -> rl.Rectangle:
  return rl.Rectangle(rect.x, rect.y + rect.height - DEV_UI_BAR_H, rect.width, DEV_UI_BAR_H)


def dev_ui_off() -> None:
  ui_state.developer_ui = DeveloperUiState.OFF


def dev_ui_bottom() -> None:
  ui_state.developer_ui = DeveloperUiState.BOTH


def main() -> int:
  print("1) 居中 / 等宽 / 在内容矩形内")
  rects = preview_button_rects(SCREEN)
  check("三个键都在", tuple(rects) == ("wide", "road", "exit"), str(tuple(rects)))
  total = 3 * PREVIEW_BTN_W + 2 * PREVIEW_BTN_PAD
  left, right = rects["wide"].x - SCREEN.x, (SCREEN.x + SCREEN.width) - (rects["exit"].x + rects["exit"].width)
  check("左右留白相等（居中）", abs(left - right) < 0.51, f"left={left:.1f} right={right:.1f} total={total}")
  check("等宽等高",
        all(r.width == PREVIEW_BTN_W and r.height == PREVIEW_BTN_H for r in rects.values()))
  check("相邻间距 = PAD",
        abs((rects["road"].x - (rects["wide"].x + rects["wide"].width)) - PREVIEW_BTN_PAD) < 1e-6)
  check("都在内容矩形内", all(r.x >= SCREEN.x and r.x + r.width <= SCREEN.x + SCREEN.width and
                              r.y >= SCREEN.y and r.y + r.height <= SCREEN.y + SCREEN.height
                              for r in rects.values()))

  print("2) 底栏关掉时不改几何（修前口径：行底距底边 PAD）")
  dev_ui_off()
  check("get_bottom_dev_ui_offset() == 0", get_bottom_dev_ui_offset() == 0)
  old_bottom = SCREEN.y + SCREEN.height - PREVIEW_BTN_H - PREVIEW_BTN_PAD
  check("行底仍在距底边 16px 处（无 reserved）",
        abs(preview_button_rects(SCREEN, get_bottom_dev_ui_offset())["wide"].y - old_bottom) < 1e-6,
        f"y={preview_button_rects(SCREEN, 0)['wide'].y:.1f} expect={old_bottom:.1f}")

  print("3) 底栏打开时按钮行让开 61px 底栏")
  dev_ui_bottom()
  reserved = get_bottom_dev_ui_offset()
  check("DevUIInfo=BOTH 时 reserved == 60", reserved == 60, f"reserved={reserved}")
  bar = dev_bar_rect(SCREEN)
  fixed = preview_button_rects(SCREEN, reserved)
  for name, r in fixed.items():
    check(f"{name} 不与底栏相交", not intersects(r, bar),
          f"button.y={r.y:.1f} bottom={r.y + r.height:.1f} bar.top={bar.y:.1f}")
    gap = bar.y - (r.y + r.height)
    check(f"{name} 与底栏间隙 >= {MIN_GAP}px", gap >= MIN_GAP, f"gap={gap:.1f}px")

  print("4) bug 见证：旧口径（不留 reserved）压在这行字上")
  legacy = preview_button_rects(SCREEN, 0)
  check("旧口径确实与底栏相交（这就是用户看到的重叠）",
        any(intersects(r, bar) for r in legacy.values()),
        f"legacy bottom={legacy['wide'].y + legacy['wide'].height:.1f} bar.top={bar.y:.1f}")

  print()
  if failures:
    print(f"FAILED: {len(failures)} 项 —— {', '.join(failures)}")
    return 1
  print("ALL PASS")
  return 0


if __name__ == "__main__":
  sys.exit(main())
