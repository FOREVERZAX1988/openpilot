"""Glyph-coverage check for the Noto fallback font choice (no display needed).

Why this exists
---------------
The language list in settings shows every language name in its own script
("한국어", "ไทย", "Українська", "日本語"). The fallback font used to be chosen
once per UI language, so in a zh-CHS UI every one of those names was drawn with
NotoSansSC - which has no Hangul/Thai glyphs and no ї (U+0457) - and raylib
silently replaced the missing glyphs with "?": the menu read "???" for Korean
and Thai and "Укра?нська" for Ukrainian. Same class of bug for ja/ko, which
pointed at the ~460-glyph NotoSansCJKjp/kr *subsets* in assets instead of the
full AGNOS fonts.

Font choice is therefore per *string*, not per UI language
(application.fallback_font_key). This test lifts that function plus the font
tables straight out of the source, runs them over every (UI language, menu
name) pair and asserts the font it picks really contains every glyph of that
name - catching the whole bug class on any machine, with no screen.

Run from the repo root:

    PYTHONPATH=. python openpilot/selfdrive/ui/tests/font_fallback_coverage.py
"""

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

APP_PY = REPO_ROOT / "openpilot/system/ui/lib/application.py"
FONT_DIR = REPO_ROOT / "openpilot/selfdrive/assets/fonts"
LANGUAGES_JSON = REPO_ROOT / "openpilot/selfdrive/ui/translations/languages.json"
PRIMARY_FONT_FILE = FONT_DIR / "Inter-Regular.ttf"

# Han glyphs the per-locale CJK fonts do not share: NotoSansJP/KR/TC carry 簡 but
# not 简, so the "中文（简体）" entry of the picker is missing a glyph while one of
# those languages is selected. Pre-existing and cosmetic (one character in one
# menu row) - listed instead of silently ignored, so a new gap cannot hide here.
KNOWN_GAPS = {
  ("ja", "中文（简体）"): "简",
  ("ko", "中文（简体）"): "简",
  ("zh-CHT", "中文（简体）"): "简",
}


def load_font_choice_helpers() -> dict:
  """Exec the real PRIMARY_FONT / NOTO_FONTS / SCRIPT_FALLBACK_FONTS / chooser.

  Importing application.py needs pyray and a GL context, so the module-level
  font tables and the pure-python chooser are lifted out of the source instead.
  """
  source = APP_PY.read_text(encoding="utf-8")
  tree = ast.parse(source)
  wanted_assigns = {"PRIMARY_FONT", "NOTO_FONTS", "SCRIPT_FALLBACK_FONTS", "_CJK_FONT_LANGUAGES", "_HAN_KANA_RE"}
  wanted_defs = {"fallback_font_key"}
  chunks: list[str] = []
  for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in wanted_assigns for t in node.targets):
      chunks.append(ast.get_source_segment(source, node))
    elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) in wanted_assigns:
      chunks.append(ast.get_source_segment(source, node))
    elif isinstance(node, ast.FunctionDef) and node.name in wanted_defs:
      chunks.append(ast.get_source_segment(source, node))
  found = {getattr(t, "id", None) for node in tree.body if isinstance(node, ast.Assign) for t in node.targets}
  found |= {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
  missing = (wanted_assigns | wanted_defs) - found
  if missing:
    raise AssertionError(f"application.py no longer defines: {sorted(missing)}")
  namespace: dict = {"re": re}
  exec("\n\n".join(chunks), namespace)
  return namespace


def resolve_font(noto_fonts: dict, primary: str, key: str) -> Path:
  """Same resolution as Application.fallback_font: absolute system font first."""
  if key == primary:
    return PRIMARY_FONT_FILE
  name = noto_fonts[key]
  if Path(name).is_absolute() and Path(name).exists():
    return Path(name)
  return FONT_DIR / Path(name).name


def main() -> int:
  ns = load_font_choice_helpers()
  primary = ns["PRIMARY_FONT"]
  noto_fonts = ns["NOTO_FONTS"]
  choose = ns["fallback_font_key"]
  languages = json.loads(LANGUAGES_JSON.read_text(encoding="utf-8"))
  names = list(languages)
  ui_languages = list(languages.values())

  failures: list[str] = []
  gaps: list[str] = []
  checks = 0
  caches: dict[Path, set[int]] = {}

  def cmap(path: Path) -> set[int]:
    if path not in caches:
      from fontTools.ttLib import TTFont
      caches[path] = set(TTFont(path, fontNumber=0, lazy=True).getBestCmap())
    return caches[path]

  # 1) every name in every UI language must be drawn with a font that has its glyphs
  for ui_lang in ui_languages:
    for name in names:
      checks += 1
      key = choose(ui_lang, name)
      if key != primary and key not in noto_fonts:
        failures.append(f"{ui_lang}: unknown font key {key!r} for {name!r}")
        continue
      path = resolve_font(noto_fonts, primary, key)
      if not path.exists():
        failures.append(f"{ui_lang}: font {path} for {name!r} does not exist")
        continue
      missing = "".join(sorted({c for c in name if ord(c) not in cmap(path) and not c.isspace()}))
      if not missing:
        continue
      expected = KNOWN_GAPS.get((ui_lang, name))
      if expected and set(missing) <= set(expected):
        gaps.append(f"{ui_lang} -> {key} ({path.name}): {name!r} missing {missing!r} (known)")
      else:
        failures.append(f"{ui_lang} -> {key} ({path.name}): {name!r} missing {missing!r} - renders as '?'")

  # 2) the scripts that actually regressed
  expectations = [
    ("zh-CHS", "한국어", "ko"), ("zh-CHT", "한국어", "ko"), ("en", "한국어", "ko"), ("ja", "한국어", "ko"),
    ("zh-CHS", "ไทย", "th"), ("en", "ไทย", "th"), ("ko", "한국어", "ko"),
    ("zh-CHS", "Українська", primary), ("en", "Українська", primary), ("ko", "Українська", primary),
    ("ja", "日本語", "ja"), ("ko", "한국어", "ko"), ("zh-CHS", "中文（简体）", "zh-CHS"),
    ("zh-CHT", "中文（繁體）", "zh-CHT"), ("en", "日本語", "zh-CHS"), ("de", "中文（简体）", "zh-CHS"),
  ]
  for ui_lang, name, expect in expectations:
    checks += 1
    got = choose(ui_lang, name)
    if got != expect:
      failures.append(f"{ui_lang} + {name!r}: expected {expect!r}, got {got!r}")

  # 3) Latin/Cyrillic strings keep the caller's own font (Inter covers them; the
  #    CJK fonts make a worse job of it and some lack ї entirely)
  for ui_lang in ui_languages:
    for name in ("English", "Deutsch", "Français", "Português", "Español", "Türkçe", "Українська"):
      checks += 1
      if choose(ui_lang, name) != primary:
        failures.append(f"{ui_lang} + {name!r}: should stay on the primary font, got {choose(ui_lang, name)!r}")

  # 4) ja/ko/cn must resolve to the full AGNOS font, not the subsets in assets
  for key in ("ja", "ko", "zh-CHS", "zh-CHT"):
    checks += 1
    path = resolve_font(noto_fonts, primary, key)
    if path.parent == FONT_DIR:
      failures.append(f"{key}: picked the subset font {path.name} from assets instead of the full "
                      f"system font - new translations render as '?'")

  print(f"UI languages: {len(ui_languages)}   menu names: {len(names)}")
  for gap in gaps:
    print(f"  known gap  {gap}")
  for failure in failures:
    print(f"  FAIL {failure}")
  print(f"\n{'FAILED' if failures else 'PASSED'} {checks - len(failures)}/{checks} checks")
  return 1 if failures else 0


if __name__ == "__main__":
  sys.exit(main())
