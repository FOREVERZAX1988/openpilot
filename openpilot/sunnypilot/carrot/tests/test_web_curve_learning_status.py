"""Web status card for the curve-speed self-learning (read-only, derived from CurvatureLearningData)."""
import unittest

from openpilot.sunnypilot.carrot.web_settings import (
  render_curve_learning_status,
  render_index,
)


class _StubParams:
  """Minimal params stand-in: the card only needs get() and get_bool()."""

  def __init__(self, learning_data: str | None = None, enabled: bool | None = False):
    self.learning_data = learning_data
    self.enabled = enabled

  def get(self, key, **kwargs):
    if key == "CurvatureLearningData":
      return self.learning_data
    raise KeyError(key)

  def get_bool(self, key):
    if key == "CscCurvatureLearningEnabled" and self.enabled is not None:
      return self.enabled
    raise KeyError(key)


class TestRenderCurveLearningStatus(unittest.TestCase):
  def test_disabled_with_no_data_shows_defaults(self):
    card = render_curve_learning_status(_StubParams())
    self.assertIn("关闭（默认）", card)
    self.assertIn("标定进度 0.0%", card)
    self.assertIn("2.0 m/s²", card)
    self.assertIn("0/24 桶", card)

  def test_enabled_with_data_shows_values(self):
    raw = '{"0.01": {"average": 2.5, "count": 400}}'
    card = render_curve_learning_status(_StubParams(learning_data=raw, enabled=True))
    self.assertIn("开启", card)
    self.assertIn("已采样 1/24 桶", card)
    self.assertIn("样本总数 400", card)

  def test_unreadable_param_key_degrades_gracefully(self):
    card = render_curve_learning_status(_StubParams(learning_data="not json", enabled=None))
    self.assertIn("未知（键不可读）", card)
    self.assertIn("标定进度 0.0%", card)

  def test_no_html_injection_through_data(self):
    raw = '{"0.01": {"average": "<script>", "count": 5}}'
    card = render_curve_learning_status(_StubParams(learning_data=raw, enabled=False))
    self.assertNotIn("<script>", card)


class TestRenderIndexExtra(unittest.TestCase):
  def test_extra_card_is_inserted_after_list(self):
    grouped = {"Driving": ["AssistSpeed"], "other": ["SomeKey"]}
    plain = render_index(grouped)
    with_card = render_index(grouped, extra=render_curve_learning_status(_StubParams()))
    self.assertNotIn("弯道速度自学习", plain)
    self.assertIn("弯道速度自学习", with_card)
    self.assertGreater(len(with_card), len(plain))
    # card content lands between the list and the footer links
    self.assertLess(with_card.index("弯道速度自学习"), with_card.index('href="/actions"'))
    self.assertGreater(with_card.index("弯道速度自学习"), with_card.index("</ul>"))


if __name__ == "__main__":
  unittest.main()
