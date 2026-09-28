#!/usr/bin/env python3
"""离屏仿真整个设置页（SettingsLayoutSP → 全部 17 个面板）。

目的：
1) 复现/防止"设置页构造崩溃"（缺 param key 等）——之前 UI 卡逗号图标就是这类问题
2) 遍历所有面板渲染，统计每帧耗时（定位"卡"）
3) 收集所有被绘制的文本，逐字符查字形 —— 缺字形就是"显示？"的来源
"""
import os, sys, time, traceback
os.environ.setdefault("OFFSCREEN", "1")
sys.path.insert(0, "/data/openpilot")

import pyray as rl
rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

from openpilot.system.ui.lib.multilang import multilang
LANG = sys.argv[1] if len(sys.argv) > 1 else "zh-CHS"
multilang.change_language(LANG)

from openpilot.system.ui.lib.application import gui_app, font_fallback
gui_app.init_window("settings sim", fps=60)

calls = []
_prev = rl.draw_text_ex
def _hook(font, text, position, font_size, spacing, tint):
    calls.append((font, text))
    return _prev(font, text, position, font_size, spacing, tint)
rl.draw_text_ex = _hook

from openpilot.selfdrive.ui.sunnypilot.layouts.settings.settings import SettingsLayoutSP

W, H = 2160, 1080
rect = rl.Rectangle(0, 0, W, H)

print(f"语言={LANG}")
t0 = time.perf_counter()
try:
    layout = SettingsLayoutSP()
except Exception:
    print("!!! SettingsLayoutSP 构造失败（这就是卡 UI 的元凶）:")
    traceback.print_exc()
    sys.exit(1)
print(f"SettingsLayoutSP 构造(含全部面板) = {(time.perf_counter()-t0)*1000:.1f} ms\n")

missing = {}
drawn = set()
failures = []
print(f"{'PANEL':<18}{'ms/frame':>10}{'draw_calls':>12}  状态")
for ptype, info in layout._panels.items():
    try:
        layout.set_current_panel(ptype)
        calls.clear()
        rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
        calls.clear()
        t0 = time.perf_counter(); N = 10
        for _ in range(N):
            rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
        dt = (time.perf_counter() - t0) / N * 1000
        for f, txt in calls:
            eff = font_fallback(f)
            drawn.add(txt)
            for ch in txt:
                if ch in "\n\t":
                    continue
                if rl.get_glyph_index(eff, ord(ch)) == 0:
                    missing.setdefault(ch, (ptype.name, txt))
        print(f"{ptype.name:<18}{dt:>10.2f}{len(calls)//N:>12}  OK")
    except Exception as e:
        failures.append((ptype.name, traceback.format_exc()))
        print(f"{ptype.name:<18}{'-':>10}{'-':>12}  FAIL: {type(e).__name__}: {e}")

print(f"\n绘制过的不同文本数 = {len(drawn)}")
print(f">>> 缺字形(会显示成乱码/空)的字符数 = {len(missing)}")
for ch, (pn, txt) in sorted(missing.items(), key=lambda kv: ord(kv[0])):
    print(f"   [{ch}] U+{ord(ch):04X}  面板={pn:<16} 例={txt[:60]!r}")

if failures:
    print(f"\n!!! {len(failures)} 个面板渲染失败:")
    for name, tb in failures:
        print(f"\n--- {name} ---\n{tb}")
