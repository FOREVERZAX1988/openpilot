from importlib.resources import files
import json
import os
import re
from typing import TYPE_CHECKING
from openpilot.common.basedir import BASEDIR
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.translations.events_i18n import TPL_MAP as EVENTS_TEMPLATES

if TYPE_CHECKING:
  from openpilot.common.params import Params
else:
  try:
    from openpilot.common.params import Params
  except (ImportError, OSError):
    Params = None

SYSTEM_UI_DIR = os.path.join(BASEDIR, "openpilot/system", "ui")
UI_DIR = files("openpilot.selfdrive.ui")
TRANSLATIONS_DIR = UI_DIR.joinpath("translations")
LANGUAGES_FILE = TRANSLATIONS_DIR.joinpath("languages.json")

FONT_FALLBACK_LANGUAGES = [
  "th",
  "zh-CHT",
  "zh-CHS",
  "ko",
  "ja",
]

# Plural form selectors for supported languages
PLURAL_SELECTORS = {
  'en': lambda n: 0 if n == 1 else 1,
  'de': lambda n: 0 if n == 1 else 1,
  'fr': lambda n: 0 if n <= 1 else 1,
  'pt-BR': lambda n: 0 if n <= 1 else 1,
  'es': lambda n: 0 if n == 1 else 1,
  'tr': lambda n: 0 if n == 1 else 1,
  'uk': lambda n: 0 if n % 10 == 1 and n % 100 != 11 else (1 if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 2),
  'ro': lambda n: 0 if n == 1 else (1 if n == 0 or 0 < n % 100 < 20 else 2),
  'th': lambda n: 0,
  'zh-CHT': lambda n: 0,
  'zh-CHS': lambda n: 0,
  'ko': lambda n: 0,
  'ja': lambda n: 0,
}


def _parse_quoted(s: str) -> str:
  """Parse a PO-format quoted string."""
  s = s.strip()
  if not (s.startswith('"') and s.endswith('"')):
    raise ValueError(f"Expected quoted string: {s!r}")
  s = s[1:-1]
  result: list[str] = []
  i = 0
  while i < len(s):
    if s[i] == '\\' and i + 1 < len(s):
      c = s[i + 1]
      if c == 'n':
        result.append('\n')
      elif c == 't':
        result.append('\t')
      elif c == '"':
        result.append('"')
      elif c == '\\':
        result.append('\\')
      else:
        result.append(s[i:i + 2])
      i += 2
    else:
      result.append(s[i])
      i += 1
  return ''.join(result)


def load_translations(path) -> tuple[dict[str, str], dict[str, list[str]]]:
  """Parse a .po file and return (translations, plurals) dicts.

  translations: msgid -> msgstr
  plurals: msgid -> [msgstr[0], msgstr[1], ...]
  """
  with path.open(encoding='utf-8') as f:
    lines = f.readlines()

  translations: dict[str, str] = {}
  plurals: dict[str, list[str]] = {}

  # Parser state
  msgid = msgid_plural = msgstr = ""
  msgstr_plurals: dict[int, str] = {}
  field: str | None = None
  plural_idx = 0

  def finish():
    nonlocal msgid, msgid_plural, msgstr, msgstr_plurals, field
    if msgid:  # skip header (empty msgid)
      if msgid_plural:
        max_idx = max(msgstr_plurals.keys()) if msgstr_plurals else 0
        plurals[msgid] = [msgstr_plurals.get(i, '') for i in range(max_idx + 1)]
      else:
        if msgstr:
          translations[msgid] = msgstr
    msgid = msgid_plural = msgstr = ""
    msgstr_plurals = {}
    field = None

  for raw in lines:
    line = raw.strip()

    if not line:
      finish()
      continue

    if line.startswith('#'):
      continue

    if line.startswith('msgid_plural '):
      msgid_plural = _parse_quoted(line[len('msgid_plural '):])
      field = 'msgid_plural'
      continue

    if line.startswith('msgid '):
      msgid = _parse_quoted(line[len('msgid '):])
      field = 'msgid'
      continue

    m = re.match(r'msgstr\[(\d+)]\s+(.*)', line)
    if m:
      plural_idx = int(m.group(1))
      msgstr_plurals[plural_idx] = _parse_quoted(m.group(2))
      field = 'msgstr_plural'
      continue

    if line.startswith('msgstr '):
      msgstr = _parse_quoted(line[len('msgstr '):])
      field = 'msgstr'
      continue

    if line.startswith('"'):
      val = _parse_quoted(line)
      if field == 'msgid':
        msgid += val
      elif field == 'msgid_plural':
        msgid_plural += val
      elif field == 'msgstr':
        msgstr += val
      elif field == 'msgstr_plural':
        msgstr_plurals[plural_idx] += val

  finish()
  return translations, plurals


class Multilang:
  def __init__(self):
    self._params = Params() if Params is not None else None
    self._language: str = "en"
    self.languages: dict[str, str] = {}
    self.codes: dict[str, str] = {}
    self._translations: dict[str, str] = {}
    self._plurals: dict[str, list[str]] = {}
    self._plural_selector = PLURAL_SELECTORS.get('en', lambda n: 0)
    # events 动态 alert 文案在 selfdrived 里就把数值拼进了字符串，UI 层拿到的
    # 是 "Drive above 30 km/h to engage" 这种成品，精确查 po 必然 miss。只对
    # events_i18n.TPL_MAP 里登记过的模板做一次反查，把数值代回中文 msgstr。
    self._templates: list[tuple[re.Pattern, str]] = []
    self._template_cache: dict[str, str] = {}
    self._load_languages()

  @property
  def language(self) -> str:
    return self._language

  def requires_font_fallback(self) -> bool:
    return self._language in FONT_FALLBACK_LANGUAGES

  def setup(self):
    try:
      po_path = TRANSLATIONS_DIR.joinpath(f'app_{self._language}.po')
      self._translations, self._plurals = load_translations(po_path)
      self._plural_selector = PLURAL_SELECTORS.get(self._language, lambda n: 0)
    except FileNotFoundError:
      cloudlog.error(f"No translation file found for language: {self._language}, using default.")
      self._translations = {}
      self._plurals = {}

    # 语言切换后模板索引与缓存都必须重建，否则会拿旧语言译文响应新语言。
    self._template_cache = {}
    self._templates = []
    for en_tpl in EVENTS_TEMPLATES.values():
      msgstr = self._translations.get(en_tpl)
      if not msgstr:
        continue
      parts = re.split(r'(\{[^}]*\})', en_tpl)
      pattern = ''.join('(.+?)' if p.startswith('{') and p.endswith('}') else re.escape(p) for p in parts)
      self._templates.append((re.compile(r'\A' + pattern + r'\Z', re.S), msgstr))
    # 具体模板优先，避免 "{}" 之类的通用模板抢先命中
    self._templates.sort(key=lambda item: -len(item[0].pattern))

  def change_language(self, language_code: str) -> None:
    self._params.put("LanguageSetting", language_code, block=True)
    self._language = language_code
    self.setup()

  def param_language(self) -> str | None:
    """The language currently stored in Params, or None if it can't be used.

    Read-only: this is the "what should we be showing" probe used to resync a UI
    that was started before the param was readable.
    """
    if self._params is None:
      return None
    try:
      code = str(self._params.get("LanguageSetting")).removeprefix("main_")
    except Exception:  # BROAD_EXCEPT_OK - a broken Params backend must not kill the UI
      return None
    return code if code in self.codes else None

  def reload(self, language_code: str) -> bool:
    """Apply a language without writing it back to Params. True if it changed."""
    if language_code == self._language or language_code not in self.codes:
      return False
    self._language = language_code
    self.setup()
    return True

  def tr(self, text: str) -> str:
    hit = self._translations.get(text)
    if hit:
      return hit
    return self._tr_template(text)

  def _tr_template(self, text: str) -> str:
    """精确查表 miss 时，按 events 模板把已拼好的数值代回译文。"""
    if not self._templates:
      return text
    cached = self._template_cache.get(text)
    if cached is not None:
      return cached
    result = text
    for pattern, msgstr in self._templates:
      m = pattern.fullmatch(text)
      if m is None:
        continue
      out = msgstr
      for group in m.groups():
        # 捕获组本身也可能是可翻译词，例如 "Calibration in Progress: 50%"
        value = self._translations.get(group, group) or group
        out = re.sub(r'\{[^}]*\}', lambda _m, v=value: v, out, count=1)
      result = out
      break
    self._template_cache[text] = result
    return result

  def trn(self, singular: str, plural: str, n: int) -> str:
    if singular in self._plurals:
      idx = self._plural_selector(n)
      forms = self._plurals[singular]
      if idx < len(forms) and forms[idx]:
        return forms[idx]
    return singular if n == 1 else plural

  def _load_languages(self):
    with LANGUAGES_FILE.open(encoding='utf-8') as f:
      self.languages = json.load(f)
    self.codes = {v: k for k, v in self.languages.items()}

    if self._params is not None:
      raw = self._params.get("LanguageSetting")
      lang = str(raw).removeprefix("main_")
      if lang in self.codes:
        self._language = lang
      else:
        # 静默回落会把整机 UI 变成英文且没人知道原因（开机那一瞬间参数目录还在
        # swap/copy 时 get() 会返回 None）。留一条证据，别再哑掉。
        cloudlog.warning(f"LanguageSetting={raw!r} unsupported -> UI language stays {self._language!r}")
    else:
      cloudlog.warning("Params backend unavailable at import -> UI language stays 'en'")


multilang = Multilang()
multilang.setup()

tr, trn = multilang.tr, multilang.trn


# no-op marker for static strings translated later
def tr_noop(s: str) -> str:
  return s
