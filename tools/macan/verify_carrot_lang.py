#!/usr/bin/env python3
"""独立验证：Carrot Tuning 在语言切换后文案是否实时更新（不重启进程）。

构造顺序：en 构造 -> 切 zh-CHS -> 再切回 en，逐次收集被绘制的文案，
断言中文/英文都真实出现（不是构造时固化的英文）。
"""
import os, sys
os.environ.setdefault("OFFSCREEN", "1")
sys.path.insert(0, "/data/openpilot")

import pyray as rl
rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

from openpilot.system.ui.lib.multilang import multilang
from openpilot.system.ui.lib.application import gui_app

def texts_for(layout, rect):
    calls = []
    prev = rl.draw_text_ex
    def hook(font, text, position, font_size, spacing, tint):
        calls.append(text)
        return prev(font, text, position, font_size, spacing, tint)
    rl.draw_text_ex = hook
    try:
        rl.begin_drawing(); rl.clear_background(rl.BLACK); layout.render(rect); rl.end_drawing()
    finally:
        rl.draw_text_ex = prev
    return calls

def has_cjk(s):
    return any('\u4e00' <= c <= '\u9fff' for c in s)

LANG0 = "en"
multilang.change_language(LANG0)
gui_app.init_window("verify", fps=60)

from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import CarrotTuningLayout
rect = rl.Rectangle(0, 0, 2160, 1080)
layout = CarrotTuningLayout(lambda: None)

fails = []
def probe(tag, lang, want_cjk):
    if multilang.language != lang:
        multilang.change_language(lang)
        gui_app.on_language_changed(lang)
    out = []
    for tab in list(layout._tab_scrollers.keys()):
        layout._current_tab = tab
        out += texts_for(layout, rect)
    cjk = [t for t in out if has_cjk(t)]
    print(f"[{tag}] lang={lang} 绘制文本={len(out)} 含中文={len(cjk)}")
    if want_cjk and not cjk:
        fails.append(f"{tag}: 期望中文却全是英文")
    if not want_cjk and cjk:
        fails.append(f"{tag}: 英文模式下仍出现中文 {cjk[:3]}")
    return cjk

print("构造语言 =", LANG0)
a = probe("construct-en", "en", want_cjk=False)
b = probe("switch-zh", "zh-CHS", want_cjk=True)
for t in b[:8]:
    print("    中文样例:", t[:50])
c = probe("back-to-en", "en", want_cjk=False)

print()
if fails:
    print("!!! FAIL:")
    for f in fails: print("   -", f)
    sys.exit(1)
print("PASS: 语言切换后 Carrot Tuning 文案实时跟随（en=英文 / zh-CHS=中文）")
