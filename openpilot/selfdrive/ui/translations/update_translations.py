#!/usr/bin/env python3
from itertools import chain
import os
from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.multilang import SYSTEM_UI_DIR, UI_DIR, TRANSLATIONS_DIR, multilang
from openpilot.selfdrive.ui.translations.potools import extract_strings, generate_pot, merge_po, init_po
from openpilot.selfdrive.ui.translations.events_i18n import inject_po

LANGUAGES_FILE = os.path.join(str(TRANSLATIONS_DIR), "languages.json")
POT_FILE = os.path.join(str(TRANSLATIONS_DIR), "app.pot")


def update_translations():
  files = []
  selfdrived_dir = os.path.join(BASEDIR, "openpilot", "selfdrive", "selfdrived")
  sp_selfdrived_dir = os.path.join(BASEDIR, "openpilot", "sunnypilot", "selfdrive", "selfdrived")
  for root, _, filenames in chain(os.walk(SYSTEM_UI_DIR),
                                  os.walk(os.path.join(str(UI_DIR), "widgets")),
                                  os.walk(os.path.join(str(UI_DIR), "layouts")),
                                  os.walk(os.path.join(str(UI_DIR), "onroad")),
                                  os.walk(os.path.join(str(UI_DIR), "sunnypilot")),
                                  os.walk(os.path.join(str(UI_DIR), "mici")),
                                  os.walk(selfdrived_dir),
                                  os.walk(sp_selfdrived_dir)):
    for filename in filenames:
      if filename.endswith(".py"):
        files.append(os.path.relpath(os.path.join(root, filename), BASEDIR))

  # Extract translatable strings and generate .pot template
  entries = extract_strings(sorted(set(files)), BASEDIR)
  generate_pot(entries, POT_FILE)

  # Generate/update translation files for each language
  for name in multilang.languages.values():
    po_file = os.path.join(str(TRANSLATIONS_DIR), f"app_{name}.po")
    if os.path.exists(po_file):
      merge_po(po_file, POT_FILE)
    else:
      init_po(POT_FILE, po_file, name)

  # events 文案是裸英文 msgid（官方写法，不带 tr/tr_noop），extract_strings 抓不到，
  # merge_po 会把它们当 obsolete 清掉。每次更新翻译后按映射表补回来，避免中文
  # 译文在下次 update_translations 时悄悄消失。
  for lang in ("zh-CHS", "zh-CHT"):
    po_file = os.path.join(str(TRANSLATIONS_DIR), f"app_{lang}.po")
    if os.path.exists(po_file):
      inject_po(po_file, lang)


if __name__ == "__main__":
  update_translations()
