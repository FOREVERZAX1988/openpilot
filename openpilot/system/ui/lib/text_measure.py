from __future__ import annotations

import pyray as rl
from openpilot.system.ui.lib.application import (FONT_SCALE, FALLBACK_FONT_SCALE, PRIMARY_FONT,
                                                  fallback_font_key, font_fallback, gui_app)
from openpilot.system.ui.lib.multilang import multilang

_cache: dict[int, rl.Vector2] = {}


def text_scale(text: str, font: rl.Font | None = None) -> float:
  """The text-size scale ``rl.draw_text_ex`` will apply to ``text``.

  Mirrors ``Application._patch_text_functions``: Latin/Cyrillic text keeps the caller's Inter
  font and is drawn at FONT_SCALE alone, while text that lands on a runtime-baked Noto subset
  is drawn at FONT_SCALE * FALLBACK_FONT_SCALE (that subset's glyphs are only ~0.68 em).

  ``font`` is the font actually used for drawing (the result of ``font_fallback()``). The
  pre-baked OpFont-<weight>-<lang>.fnt atlases carry Inter's metrics, so they must NOT get the
  extra fallback scale -- otherwise every CJK string renders 25% bigger than the Latin text
  next to it. Passing ``None`` assumes the worst case (runtime Noto subset).
  """
  key = fallback_font_key(multilang.language, text) if isinstance(text, str) else multilang.language
  if not (multilang.requires_font_fallback() and key != PRIMARY_FONT):
    return FONT_SCALE
  return FONT_SCALE * (gui_app.fallback_scale(font) if font is not None else FALLBACK_FONT_SCALE)


def measure_text_cached(font: rl.Font, text: str, font_size: int, spacing: float = 0) -> rl.Vector2:
  """Caches text measurements to avoid redundant calculations."""
  font = font_fallback(font, text)
  spacing = round(spacing, 4)
  key = hash((font.texture.id, text, font_size, spacing))
  if key in _cache:
    return _cache[key]

  result = rl.measure_text_ex(font, text, font_size * text_scale(text, font), spacing)  # noqa: TID251

  _cache[key] = result
  return result


def clear_cache() -> None:
  """Drop every entry. Keys embed font.texture.id, and raylib recycles those, so entries
  measured against a replaced font atlas would otherwise be returned for the new one."""
  _cache.clear()
