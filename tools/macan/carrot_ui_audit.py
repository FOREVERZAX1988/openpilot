#!/usr/bin/env python3
"""离屏审计 Carrot Tuning 设置页（v3）

1) 渲染根页 + 全部分组子页，捕获每次 draw_text_ex（含实际生效字体）
2) 缺字形的字符会被画成 "?" → 直接定位"显示 ?"
   （判法见 ui_audit_lib.missing_glyph：本仓 raylib 打了补丁，get_glyph_index 不可信）
3) 统计构造耗时 / 每帧耗时 / 绘制调用数（定位"卡"）
4) 被当图片画出来的 emoji（emoji 图集）单独计数，不算缺字形

页面结构：CarrotTuningLayout 早先是"每个 tab 一个 scroller"（_tab_scrollers/_current_tab），
现已改成"根页 + 按需构造的分组子页"（_group_layouts/_current_group），遍历走
ui_audit_lib.carrot_pages。
"""
import json
import sys
import time

from ui_audit_lib import DrawRecorder, carrot_item_count, carrot_pages, emoji_atlas_ids, missing_glyph

import pyray as rl
rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

from openpilot.system.ui.lib.multilang import multilang

LANG = sys.argv[1] if len(sys.argv) > 1 else "zh-CHS"
multilang.change_language(LANG)

from openpilot.system.ui.lib.application import gui_app, font_fallback
gui_app.init_window("carrot audit", fps=60)

from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import CarrotTuningLayout

missing = {}      # char -> 例子文本
drawn_texts = set()


def check(font, text):
    eff = font_fallback(font, text)          # 绘制路径实际生效的字体
    for ch in text:
        if ch in "\n\t ":
            continue
        if missing_glyph(eff, ch):
            missing.setdefault(ch, text)
    drawn_texts.add(text)


t0 = time.perf_counter()
layout = CarrotTuningLayout(lambda: None)
t_construct = time.perf_counter() - t0

W, H = 2160, 1080
rect = rl.Rectangle(0, 0, W, H)

rec = DrawRecorder()
per_page = []
emoji_drawn = 0
for name, key in carrot_pages(layout):
    layout._set_current_group(key)

    # 采样帧：查缺字形 + 数 draw call
    rec.clear()
    with rec:
        rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
    frame_calls = len(rec.texts)
    atlas = emoji_atlas_ids()
    emoji_drawn += sum(1 for tid in rec.texture_ids if tid in atlas)
    for f, txt in rec.texts:
        check(f, txt)

    # 计时帧（不记录）
    t0 = time.perf_counter(); N = 20
    for _ in range(N):
        rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
    dt = (time.perf_counter() - t0) / N

    per_page.append((name, carrot_item_count(layout, key), frame_calls, dt * 1000))

fb = gui_app.fallback_font()
print(f"\n语言={LANG}  CarrotTuningLayout 构造耗时 = {t_construct*1000:.1f} ms")
print(f"fallback 字体: glyphCount={fb.glyphCount} baseSize={fb.baseSize} tex={fb.texture.width}x{fb.texture.height}")
print(f"\n{'PAGE':<12}{'items':>7}{'draw_calls':>12}{'ms/frame':>11}")
for name, n, c, ms in per_page:
    print(f"{name:<12}{n:>7}{c:>12}{ms:>11.2f}")
print(f"合计 item 数 = {sum(n for _, n, _, _ in per_page)}")

print(f"\n绘制过的不同文本数 = {len(drawn_texts)}")
print(f"emoji 图集绘制次数 = {emoji_drawn}  （作为图片画出来，不计缺字形）")
print(f"\n>>> 缺字形（会显示成 \"?\"）的字符数 = {len(missing)}")
for ch, ex in sorted(missing.items(), key=lambda kv: ord(kv[0]))[:60]:
    print(f"   [{ch}] U+{ord(ch):04X}  例: {ex[:70]!r}")

json.dump({"missing": {ch: ex for ch, ex in missing.items()},
           "construct_ms": t_construct * 1000,
           "per_page": [{"page": n, "items": i, "calls": c, "ms": m} for n, i, c, m in per_page]},
          open("/data/openpilot/tools/macan/carrot_ui_audit.json", "w"), ensure_ascii=False, indent=1)
print("\n已写出 tools/macan/carrot_ui_audit.json")
