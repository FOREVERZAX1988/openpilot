#!/usr/bin/env python3
"""Macan UI 离屏审计共用件：缺字形检测 + Carrot Tuning 页面遍历 + 绘制捕获。

为什么不用 rl.get_glyph_index 判"缺字形"
------------------------------------------------------------------
本仓 raylib 是打过补丁的（启动日志里的 "FONT: Requested codepoints glyphs found: [n/m]"
就是它打的），它自带一层系统字体 fallback，而且**缺字形时返回的索引不是 0**。所以
`rl.get_glyph_index(font, ord(ch)) == 0` 这种判法在本机会全判"通过"——2026-10 就是这样
漏掉了 SunyLink 标题里的 🚀（英文/拉丁界面下画成 "?"，只有中文界面因为译文是
"★ SunnyLink ★" 才躲过去）。

可靠判法：把字符真画一遍，和 "?" 的像素签名比对（同形即缺字形）。
"""
import os
import sys

os.environ.setdefault("OFFSCREEN", "1")
sys.path.insert(0, "/data/openpilot")

import pyray as rl

CANVAS = (240, 160)
FONT_SIZE = 60
_qmark_sig: dict[tuple[int, int], tuple[int, ...]] = {}


def ink_signature(font, ch: str, font_size: int = FONT_SIZE) -> tuple[int, ...]:
    """把单个字符画进离屏纹理，返回"逐行前景像素数"作为形状指纹。"""
    rt = rl.load_render_texture(*CANVAS)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.BLACK)
    rl.draw_text_ex(font, ch, rl.Vector2(10, 10), font_size, 0, rl.WHITE)
    rl.end_texture_mode()
    img = rl.load_image_from_texture(rt.texture)
    # 一次性取回像素数组：逐像素调 rl.get_image_color 要 0.2~0.9s/字符，太慢。
    colors = rl.load_image_colors(img)
    w, h = img.width, img.height
    sig = tuple(sum(1 for x in range(w) if colors[y * w + x].r > 40) for y in range(h))
    rl.unload_image_colors(colors)
    rl.unload_image(img)
    rl.unload_render_texture(rt)
    return sig


_missing_cache: dict[tuple[int, int, str], bool] = {}


def missing_glyph(font, ch: str) -> bool:
    """用 ``font`` 画 ``ch`` 会不会画成 "?"（含 raylib 自带的 fallback 链）。

    每次判定要真渲染一张纹理，所以按 (字体, 字符) 缓存——审计要遍历上百个字符。

    "?" 本身永远返回 False：缺字形时画的就是 "?"，两者形状无法区分，而文案里的问号
    绝大多数是真问号（例：FIREHOSE 页 "Does it matter how or where I drive?"）。
    """
    if ch == "?":
        return False
    key = (font.texture.id, font.glyphCount, ch)
    if key not in _missing_cache:
        font_key = (font.texture.id, font.glyphCount)
        if font_key not in _qmark_sig:
            _qmark_sig[font_key] = ink_signature(font, "?")
        _missing_cache[key] = ink_signature(font, ch) == _qmark_sig[font_key]
    return _missing_cache[key]


class DrawRecorder:
    """临时接管 rl.draw_text_ex / rl.draw_texture_ex，收集"这一帧画了什么"。

    ``texts`` 记 (字体, 文本)——字体是调用方实际传给 draw_text_ex 的那个（含 label
    自己算出来的 fallback）。``texture_ids`` 用来识别 emoji 图集绘制，那些字符是当图片
    画的，不能算缺字形。
    """

    def __init__(self):
        self.texts: list[tuple[object, str]] = []
        self.texture_ids: list[int] = []
        self._prev_text = rl.draw_text_ex
        self._prev_tex = rl.draw_texture_ex

    def __enter__(self):
        def text_hook(font, text, position, font_size, spacing, tint):
            self.texts.append((font, text))
            return self._prev_text(font, text, position, font_size, spacing, tint)

        def tex_hook(texture, position, rotation, scale, tint):
            self.texture_ids.append(texture.id)
            return self._prev_tex(texture, position, rotation, scale, tint)

        rl.draw_text_ex = text_hook
        rl.draw_texture_ex = tex_hook
        return self

    def __exit__(self, *_exc):
        rl.draw_text_ex = self._prev_text
        rl.draw_texture_ex = self._prev_tex
        return False

    def clear(self):
        self.texts.clear()
        self.texture_ids.clear()


def emoji_atlas_ids() -> set[int]:
    """emoji 图集纹理 id（被当图片画出来的 emoji，别误判成缺字形）。"""
    from openpilot.system.ui.lib import emoji as emoji_lib
    return {tex.id for tex in emoji_lib._cache.values()}


def carrot_pages(layout):
    """(页面名, key)：根页 + 每个分组子页。key=None 表示根页。

    CarrotTuningLayout 早先是"每个 tab 一个 scroller"（_tab_scrollers/_current_tab），
    现已改成"根页 + 按需构造的分组子页"（_group_layouts/_current_group），这里跟着走。
    """
    from openpilot.selfdrive.ui.sunnypilot.layouts.settings.carrot_tuning import CarrotGroupKey

    yield "ROOT", None
    for key in CarrotGroupKey:
        yield key.name, key


def carrot_item_count(layout, key) -> int:
    if key is None:
        return len(layout._scroller._items)
    group = layout._group_layouts.get(key)
    return len(group._scroller._items) if group is not None else 0
