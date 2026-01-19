#!/usr/bin/env python3
from pathlib import Path
import json
import sys

import pyray as rl

# 設定 OpenPilot 的根目錄
# 通常是 /data/openpilot/selfdrive
FONT_DIR = Path(__file__).resolve().parent
SELFDRIVE_DIR = Path("/data/openpilot/selfdrive")
TRANSLATIONS_DIR = SELFDRIVE_DIR / "ui" / "translations"
LANGUAGES_FILE = TRANSLATIONS_DIR / "languages.json"

GLYPH_PADDING = 6
EXTRA_CHARS = "–‑✓×°§•X⚙✕◀▶✔⌫⇧␣○●↳çêüñ–‑✓×°§•€£¥"
UNIFONT_LANGUAGES = {"ar", "th", "zh-CHT", "zh-CHS", "ko", "ja"}


def _languages():
  if not LANGUAGES_FILE.exists():
    return {}
  with LANGUAGES_FILE.open(encoding="utf-8") as f:
    return json.load(f)


def _char_sets():
  base = set(map(chr, range(32, 127))) | set(EXTRA_CHARS)

  # --- 新增：讀取 CHANGELOGS.md ---
  # OpenPilot 根目錄通常是 selfdrive 的上一層
  changelog_path = SELFDRIVE_DIR.parent / "CHANGELOGS.md"
  
  print(f"\n--- Checking {changelog_path} ---")
  if changelog_path.exists():
      try:
          content = changelog_path.read_text(encoding="utf-8")
          chars = set(content)
          base.update(chars)
          print(f"SUCCESS: Added {len(chars)} characters from CHANGELOGS.md")
      except Exception as e:
          print(f"ERROR: Could not read CHANGELOGS.md: {e}")
  else:
      print("WARNING: CHANGELOGS.md not found! (Characters in logs might be missing)")
  print("-------------------------------\n")
  # --- 讀取結束 ---

  # --- 新增：多路徑搜尋 events.py ---
  # 我們會依序檢查這些位置，找到第一個存在的就讀取
  possible_paths = [
      # 1. 您提供的路徑 (優先檢查)
      Path("/data/openpilot/selfdrive/selfdrived/events.py"),
      SELFDRIVE_DIR / "selfdrived" / "events.py",
      
      # 2. 官方標準路徑 (作為備用)
      SELFDRIVE_DIR / "controls" / "lib" / "events.py",
      Path("/data/openpilot/selfdrive/controls/lib/events.py"),
  ]

  found = False
  print("\n--- Searching for events.py ---")
  for events_path in possible_paths:
      print(f"DEBUG: Checking: {events_path}")
      if events_path.exists():
          print(f"SUCCESS: Found events.py at {events_path}")
          try:
              # 讀取檔案內容
              content = events_path.read_text(encoding="utf-8")
              chars = set(content)
              base.update(chars)
              print(f"SUCCESS: Added {len(chars)} characters from events.py")
              found = True
              break
          except Exception as e:
              print(f"ERROR: Could not read file: {e}")
  
  if not found:
      print("WARNING: Could not find events.py in any known location!")
      print("WARNING: Chinese characters WILL BE MISSING in the output images.")
  print("-------------------------------\n")
  # --- 搜尋結束 ---

  unifont = set(base)

  for language, code in _languages().items():
    unifont.update(language)
    for prefix in ("app_", "dragonpilot_"):
      po_path = TRANSLATIONS_DIR / f"{prefix}{code}.po"
      try:
        chars = set(po_path.read_text(encoding="utf-8"))
      except FileNotFoundError:
        continue
      (unifont if code in UNIFONT_LANGUAGES else base).update(chars)

  return tuple(sorted(ord(c) for c in base)), tuple(sorted(ord(c) for c in unifont))


def _glyph_metrics(glyphs, rects, codepoints):
  entries = []
  min_offset_y, max_extent = None, 0
  for idx, codepoint in enumerate(codepoints):
    glyph = glyphs[idx]
    rect = rects[idx]
    width = int(round(rect.width))
    height = int(round(rect.height))
    offset_y = int(round(glyph.offsetY))
    min_offset_y = offset_y if min_offset_y is None else min(min_offset_y, offset_y)
    max_extent = max(max_extent, offset_y + height)
    entries.append({
      "id": codepoint,
      "x": int(round(rect.x)),
      "y": int(round(rect.y)),
      "width": width,
      "height": height,
      "xoffset": int(round(glyph.offsetX)),
      "yoffset": offset_y,
      "xadvance": int(round(glyph.advanceX)),
    })

  if min_offset_y is None:
    raise RuntimeError("No glyphs were generated")

  line_height = int(round(max_extent - min_offset_y))
  base = int(round(max_extent))
  return entries, line_height, base


def _write_bmfont(path: Path, font_size: int, face: str, atlas_name: str, line_height: int, base: int, atlas_size, entries):
  if line_height != font_size:
    line_height = font_size
  lines = [
    f"info face=\"{face}\" size=-{font_size} bold=0 italic=0 charset=\"\" unicode=1 stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=0,0 outline=0",
    f"common lineHeight={line_height} base={base} scaleW={atlas_size[0]} scaleH={atlas_size[1]} pages=1 packed=0 alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4",
    f"page id=0 file=\"{atlas_name}\"",
    f"chars count={len(entries)}",
  ]
  for entry in entries:
    lines.append(
      ("char id={id:<4} x={x:<5} y={y:<5} width={width:<5} height={height:<5} " +
       "xoffset={xoffset:<5} yoffset={yoffset:<5} xadvance={xadvance:<5} page=0  chnl=15").format(**entry)
    )
  path.write_text("\n".join(lines) + "\n")


def _process_font(font_path: Path, codepoints: tuple[int, ...]):
  print(f"Processing {font_path.name}...")

  font_size = {
    "unifont.otf": 60,
  }.get(font_path.name, 350)

  data = font_path.read_bytes()
  file_buf = rl.ffi.new("unsigned char[]", data)
  cp_buffer = rl.ffi.new("int[]", codepoints)
  cp_ptr = rl.ffi.cast("int *", cp_buffer)
  glyphs = rl.load_font_data(rl.ffi.cast("unsigned char *", file_buf), len(data), font_size, cp_ptr, len(codepoints), rl.FontType.FONT_DEFAULT)
  if glyphs == rl.ffi.NULL:
    raise RuntimeError("raylib failed to load font data")

  rects_ptr = rl.ffi.new("Rectangle **")
  image = rl.gen_image_font_atlas(glyphs, rects_ptr, len(codepoints), font_size, GLYPH_PADDING, 0)
  if image.width == 0 or image.height == 0:
    raise RuntimeError("raylib returned an empty atlas")

  rects = rects_ptr[0]
  atlas_name = f"{font_path.stem}.png"
  atlas_path = FONT_DIR / atlas_name
  entries, line_height, base = _glyph_metrics(glyphs, rects, codepoints)

  if not rl.export_image(image, atlas_path.as_posix()):
    raise RuntimeError("Failed to export atlas image")

  _write_bmfont(FONT_DIR / f"{font_path.stem}.fnt", font_size, font_path.stem, atlas_name, line_height, base, (image.width, image.height), entries)


def main():
  print(f"DEBUG: Script started in {FONT_DIR}")
  base_cp, unifont_cp = _char_sets()
  fonts = sorted(FONT_DIR.glob("*.ttf")) + sorted(FONT_DIR.glob("*.otf"))
  for font in fonts:
    if "emoji" in font.name.lower():
      continue
    glyphs = unifont_cp if font.stem.lower().startswith("unifont") else base_cp
    _process_font(font, glyphs)
  return 0


if __name__ == "__main__":
  try:
      main()
  except Exception as e:
      print(f"FATAL ERROR: {e}")
      sys.exit(1)
