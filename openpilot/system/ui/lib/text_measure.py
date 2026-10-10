import pyray as rl
from openpilot.system.ui.lib.application import (FONT_SCALE, FALLBACK_FONT_SCALE, PRIMARY_FONT,
                                                  fallback_font_key, font_fallback)
from openpilot.system.ui.lib.multilang import multilang

_cache: dict[int, rl.Vector2] = {}


def text_scale(text: str) -> float:
  """The text-size scale ``rl.draw_text_ex`` will apply to ``text``.

  Mirrors ``Application._patch_text_functions``: Latin/Cyrillic text keeps the caller's Inter
  font and is drawn at FONT_SCALE alone, while text that actually switches to a Noto fallback
  font is drawn at FONT_SCALE * FALLBACK_FONT_SCALE. Measuring every string with the fallback
  scale made centered Latin text sit (FALLBACK_FONT_SCALE - 1) / 2 of its width too close to
  the start edge -- that is what pushed the "SUNNYLINK" metric label in the left sidebar under
  the colored bar instead of leaving it centered.
  """
  key = fallback_font_key(multilang.language, text) if isinstance(text, str) else multilang.language
  needs_fallback_scale = multilang.requires_font_fallback() and key != PRIMARY_FONT
  return FONT_SCALE * (FALLBACK_FONT_SCALE if needs_fallback_scale else 1.0)


def measure_text_cached(font: rl.Font, text: str, font_size: int, spacing: float = 0) -> rl.Vector2:
  """Caches text measurements to avoid redundant calculations."""
  font = font_fallback(font, text)
  spacing = round(spacing, 4)
  key = hash((font.texture.id, text, font_size, spacing))
  if key in _cache:
    return _cache[key]

  result = rl.measure_text_ex(font, text, font_size * text_scale(text), spacing)  # noqa: TID251

  _cache[key] = result
  return result


def clear_cache() -> None:
  """Drop every entry. Keys embed font.texture.id, and raylib recycles those, so entries
  measured against a replaced font atlas would otherwise be returned for the new one."""
  _cache.clear()
