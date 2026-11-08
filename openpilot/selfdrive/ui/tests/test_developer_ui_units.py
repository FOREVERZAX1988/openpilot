"""Regression for the zh-CHS onroad-preview UI restart loop (2026-11-08).

elements.py stores right-hand developer-UI units as tr(...) results. The rotated
unit texture cache used to be keyed by raw English msgids, so once the Chinese
po files were populated tr("m/s^2") returned "m/s²" and tr("km/h") returned
"公里/时". The first rendered acceleration row raised

    KeyError: 'm/s²'

in _draw_right_dev_ui_element(); manager kept relaunching ui forever. Opening
onroad preview is what made that branch render on a Chinese device.
"""
import ast
from pathlib import Path

import pytest

from openpilot.system.ui.lib.multilang import multilang, tr

DEV_UI_DIR = Path(__file__).resolve().parents[1] / "sunnypilot" / "onroad" / "developer_ui"
INIT_PY = DEV_UI_DIR / "__init__.py"
ELEMENTS_PY = DEV_UI_DIR / "elements.py"

# The bottom dev UI draws units inline via draw_text_ex(element.unit_text); only
# the right-hand column uses the rotated _unit_textures cache. Steering torque is
# bottom-only, so it is deliberately absent from RIGHT_UNITS -- and the .get()
# fallback keeps it harmless even if it is ever moved to the right column.
BOTTOM_ONLY_UNIT_MSGIDS = {"N·dm"}


@pytest.fixture
def restore_language():
  previous = multilang.language
  yield
  if multilang.language != previous:
    multilang.reload(previous)


def _right_units() -> set[str]:
  tree = ast.parse(INIT_PY.read_text(encoding="utf-8"))
  for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RIGHT_UNITS" for t in node.targets):
      return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
  raise AssertionError("RIGHT_UNITS not found in developer_ui/__init__.py")


def _element_unit_msgids() -> set[str]:
  """Every string literal passed to tr() in a `self.unit = ...` assignment."""
  tree = ast.parse(ELEMENTS_PY.read_text(encoding="utf-8"))
  found: set[str] = set()

  def collect(expr):
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "tr":
      if expr.args and isinstance(expr.args[0], ast.Constant) and isinstance(expr.args[0].value, str):
        found.add(expr.args[0].value)
    for child in ast.iter_child_nodes(expr):
      collect(child)

  for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
      isinstance(target, ast.Attribute) and target.attr == "unit" for target in node.targets
    ):
      collect(node.value)
  return found


def _right_element_unit_msgids() -> set[str]:
  return _element_unit_msgids() - BOTTOM_ONLY_UNIT_MSGIDS


def test_every_right_dev_ui_unit_is_registered():
  missing = _right_element_unit_msgids() - _right_units()
  assert not missing, f"units missing from RIGHT_UNITS (would KeyError while rendering): {missing}"


def test_translated_keys_cover_zh_chs(restore_language):
  multilang.reload("zh-CHS")
  translated = {tr(unit) for unit in _right_units()}
  element_units = {tr(unit) for unit in _right_element_unit_msgids()}
  assert element_units <= translated
  # The exact regression: the po file translates the ASCII caret to a Unicode superscript.
  assert tr("m/s^2") == "m/s²"
  assert "m/s²" in translated
  assert tr("km/h") == "公里/时"


def test_cache_is_language_aware_and_lookup_is_safe():
  src = INIT_PY.read_text(encoding="utf-8")
  assert "tr(unit)" in src, "unit texture keys must follow the active language"
  assert "self._unit_textures.get(element.unit)" in src, "a missing unit must never crash the UI process"
  assert "self._unit_textures[element.unit]" not in src
