"""Guard tests for the Carrot Tuning top tab bar (Settings -> Navigation -> Carrot Tuning).

The tab strip is the only thing drawn at the top of that page, and it used a 24 px font
while the list items right underneath it use 50 px, so it read as "too small" on the
device. It is now 1.5x (36 px).

1.5x is safe for the two-character Chinese labels but not for every language: a latin
label such as "Navigation" is several times wider than "导航", and one tab is only
screen_width/9 wide, so each label is fitted to its tab instead of being drawn past the
edge of it. These tests pin both halves of that behaviour.
"""
import pathlib
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.ui.sunnypilot.layouts.settings import carrot_tuning as ct

# tizi / comma 3X geometry, as the UI itself computes it.
FONT_SCALE = 1.242       # application.FONT_SCALE for BIG_UI
CJK_EXTRA_SCALE = 1.25   # application.FALLBACK_FONT_SCALE used for CJK strings
SCREEN_W = 2160
SIDEBAR_W = 500          # selfdrive/ui/layouts/settings/settings.py: SIDEBAR_WIDTH
PANEL_MARGIN = 50        # ditto: PANEL_MARGIN
TAB_W = (SCREEN_W - SIDEBAR_W - 2 * PANEL_MARGIN) / ct.CarrotTuningLayout.TAB_COUNT

PREVIOUS_FONT_SIZE = 24
ZH_LABELS = ('开始', '巡航', '导航', '速度', '调节', '显示', '轨迹', '车辆', '开发者')


def _measure(font, text: str, font_size: int, spacing: float = 0):
  """Stand-in for measure_text_cached(), which needs a window / GPU context.

  Advance widths model Inter (latin ~0.5 em) and Noto CJK (1 em, scaled by the fallback
  factor) - that mix is what makes the three-character 开发者 the widest Chinese label.
  """
  width = 0.0
  for ch in text:
    cjk = ord(ch) > 0x2E80
    width += font_size * FONT_SCALE * (CJK_EXTRA_SCALE * 1.0 if cjk else 0.5)
  return SimpleNamespace(x=width, y=font_size * FONT_SCALE)


class TestCarrotTuningTabBar(unittest.TestCase):
  def setUp(self):
    original = ct.measure_text_cached
    ct.measure_text_cached = _measure
    self.addCleanup(lambda: setattr(ct, "measure_text_cached", original))

  def _fit(self, label: str):
    return ct.CarrotTuningLayout._fit_tab_label(None, label, TAB_W)

  def test_font_is_one_and_a_half_times_the_previous_size(self):
    self.assertEqual(ct.TAB_FONT_SIZE, PREVIOUS_FONT_SIZE * 1.5)

  def test_shrink_floor_never_goes_below_the_old_size(self):
    """A long label may not end up smaller than it was before the bump."""
    self.assertGreaterEqual(ct.TAB_FONT_MIN_SIZE, PREVIOUS_FONT_SIZE)

  def test_tab_bar_is_tall_enough_for_the_bigger_labels(self):
    # 36 px * FONT_SCALE * fallback scale is ~56 px of glyph height.
    required = ct.TAB_FONT_SIZE * FONT_SCALE * CJK_EXTRA_SCALE + 20
    self.assertGreaterEqual(ct.CarrotTuningLayout.TAB_HEIGHT, required)

  def test_no_label_is_drawn_past_the_edge_of_its_tab(self):
    for label in ct.CarrotTuningLayout.TAB_KEYS + ZH_LABELS:
      with self.subTest(label=label):
        self.assertLessEqual(self._fit(label)[1].x, TAB_W)

  def test_chinese_labels_respect_the_tab_padding(self):
    max_width = TAB_W - 2 * ct.TAB_TEXT_PADDING
    for label in ZH_LABELS:
      with self.subTest(label=label):
        self.assertLessEqual(self._fit(label)[1].x, max_width + 1e-6)

  def test_chinese_labels_keep_the_full_size(self):
    """The bump has to actually reach the screen in the user's language."""
    shrunk = [label for label in ZH_LABELS if self._fit(label)[0] < ct.TAB_FONT_SIZE]
    self.assertLessEqual(len(shrunk), 1, f"中文标签被过度缩放: {shrunk}")

  def test_short_labels_are_untouched(self):
    for label in ('开始', '轨迹', 'Path', 'Start'):
      with self.subTest(label=label):
        self.assertEqual(self._fit(label)[0], ct.TAB_FONT_SIZE)

  def test_long_latin_label_shrinks_but_stays_readable(self):
    font_size, measured = self._fit('Navigation')
    self.assertLess(font_size, ct.TAB_FONT_SIZE)
    self.assertGreaterEqual(font_size, ct.TAB_FONT_MIN_SIZE)
    self.assertLessEqual(measured.x, TAB_W)

  def test_draw_call_uses_the_fitted_size(self):
    """Reverting the draw call to a hard-coded TAB_FONT_SIZE would clip latin labels."""
    src = pathlib.Path(ct.__file__).read_text(encoding="utf-8")
    self.assertIn("_fit_tab_label(tab_font, label, tab_w)", src)
    self.assertNotIn("TAB_FONT_SIZE, 0, text_color", src)


if __name__ == '__main__':
  unittest.main()
