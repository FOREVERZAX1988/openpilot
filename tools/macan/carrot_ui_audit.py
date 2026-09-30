#!/usr/bin/env python3
"""离屏审计 Carrot Tuning 设置面板（v2）

1) 渲染所有 tab，捕获每次 draw_text_ex（含最终生效字体）→ 逐字符查字形
2) 缺字形的字符会被 raylib 画成 glyphs[0]（本机上是 '?'）→ 直接定位"显示？"
3) 统计构造耗时 / 每帧耗时 / 绘制调用数（定位"卡"）
"""
import os, sys, time
os.environ.setdefault("OFFSCREEN", "1")
sys.path.insert(0, "/data/openpilot")

import pyray as rl
rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

from openpilot.system.ui.lib.multilang import multilang
LANG = sys.argv[1] if len(sys.argv) > 1 else "zh-CHS"
multilang.change_language(LANG)

from openpilot.system.ui.lib.application import gui_app
gui_app.init_window("carrot audit", fps=60)

calls = []
_prev_draw = rl.draw_text_ex
def _hook(font, text, position, font_size, spacing, tint):
    calls.append((font, text, font_size))
    return _prev_draw(font, text, position, font_size, spacing, tint)
rl.draw_text_ex = _hook

from openpilot.system.ui.lib.application import font_fallback
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import CarrotTuningLayout

# ---------- 缺字形统计 ----------
missing = {}      # char -> (例子文本, 是否真正绘制时用的字体)
drawn_texts = set()

def check(font, text):
    eff = font_fallback(font)          # 绘制路径实际生效的字体
    for ch in text:
        if ch in "\n\t":
            continue
        if rl.get_glyph_index(eff, ord(ch)) == 0 and ord(ch) != ord(eff.glyphs[0].value):
            missing.setdefault(ch, text)
    drawn_texts.add(text)

t0 = time.perf_counter()
layout = CarrotTuningLayout(lambda: None)
t_construct = time.perf_counter() - t0

W, H = 2160, 1080
rect = rl.Rectangle(0, 0, W, H)

per_tab = []
for tab in list(layout._tab_scrollers.keys()):
    layout._current_tab = tab
    calls.clear()
    rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
    calls.clear()
    t0 = time.perf_counter(); N = 20
    for _ in range(N):
        rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
    dt = (time.perf_counter() - t0) / N
    for f, txt, _ in calls:
        check(f, txt)
    n_items = len(getattr(layout, f"_{tab.name.lower()}_items", []))
    per_tab.append((tab.name, n_items, len(calls), dt * 1000))

fb = gui_app.fallback_font()
print(f"\n语言={LANG}  CarrotTuningLayout 构造耗时 = {t_construct*1000:.1f} ms")
print(f"fallback 字体: glyphCount={fb.glyphCount} baseSize={fb.baseSize} tex={fb.texture.width}x{fb.texture.height}")
print(f"glyphs[0].value = {fb.glyphs[0].value!r}  ({chr(fb.glyphs[0].value)!r})  <- 缺字形时画的就是它")
print(f"\n{'TAB':<9}{'items':>7}{'draw_calls':>12}{'ms/frame':>11}")
for name, n, c, ms in per_tab:
    print(f"{name:<9}{n:>7}{c:>12}{ms:>11.2f}")
tot_items = sum(n for _, n, _, _ in per_tab)
print(f"合计 item 数 = {tot_items}")

print(f"\n绘制过的不同文本数 = {len(drawn_texts)}")
print(f"\n>>> 缺字形（会显示成 {chr(fb.glyphs[0].value)!r}）的字符数 = {len(missing)}")
for ch, ex in sorted(missing.items(), key=lambda kv: ord(kv[0]))[:60]:
    print(f"   [{ch}] U+{ord(ch):04X}  例: {ex[:70]!r}")

import json
json.dump({"missing": {ch: ex for ch, ex in missing.items()},
           "construct_ms": t_construct * 1000,
           "per_tab": [{"tab": n, "items": i, "calls": c, "ms": m} for n, i, c, m in per_tab]},
          open("/data/openpilot/tools/macan/carrot_ui_audit.json", "w"), ensure_ascii=False, indent=1)
print("\n已写出 tools/macan/carrot_ui_audit.json")
