"""events i18n 迁移回归：中文界面逐字不变 + 语言切换真正生效。

1108 之前的状况：上游 mouxa/test 把官方英文 alert 文案硬编码成中文，
tr() 查 po 永远 miss，LanguageSetting 切到任何语言都显示中文。
迁移后源码存英文 msgid、中文原文进 po，本测试锁住这个契约。
"""
import ast
import os
import re
import pytest

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.translations.events_i18n import CONST_MAP, TPL_MAP, po_entries

EVENTS_FILES = [
  "openpilot/selfdrive/selfdrived/events.py",
  "openpilot/sunnypilot/selfdrive/selfdrived/events.py",
  "openpilot/sunnypilot/selfdrive/selfdrived/events_base.py",
  "openpilot/sunnypilot/selfdrive/selfdrived/events_zp.py",
]
PO_FILES = ("zh-CHS", "zh-CHT")


def _has_cn(s: str) -> bool:
  return any("\u4e00" <= c <= "\u9fff" for c in s)


@pytest.fixture
def restore_language():
  from openpilot.system.ui.lib.multilang import multilang
  original = multilang.language
  yield multilang
  multilang.reload(original)


def test_events_source_has_no_hardcoded_chinese():
  """源码里不许再出现中文字符串常量（docstring / 注释豁免）。"""
  for rel in EVENTS_FILES:
    path = os.path.join(BASEDIR, rel)
    tree = ast.parse(open(path, encoding="utf-8").read())
    parents: dict[ast.AST, ast.AST] = {}
    for n in ast.walk(tree):
      for c in ast.iter_child_nodes(n):
        parents[c] = n
    hits = [
      (n.lineno, n.value[:30]) for n in ast.walk(tree)
      if isinstance(n, ast.Constant) and isinstance(n.value, str) and _has_cn(n.value)
      and not isinstance(parents.get(n), ast.Expr)
    ]
    assert not hits, f"{rel} 仍有硬编码中文: {hits[:5]}"


def test_chinese_po_covers_every_msgid():
  """每个 events msgid 在中文 po 里都有译文，且与 fork 原中文逐字一致。"""
  def unesc(s: str) -> str:
    return s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")

  for lang in PO_FILES:
    po = os.path.join(BASEDIR, "openpilot/selfdrive/ui/translations", f"app_{lang}.po")
    content = open(po, encoding="utf-8").read()
    existing: dict[str, str] = {}
    for m in re.finditer(r'msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', content):
      existing.setdefault(unesc(m.group(1)), unesc(m.group(2)))
    missing = [mid for mid, _ in po_entries() if mid not in existing]
    wrong = [(mid, existing[mid], want) for mid, want in po_entries()
             if mid in existing and existing[mid] != want]
    assert not missing, f"app_{lang}.po 缺 {len(missing)} 条: {missing[:5]}"
    assert not wrong, f"app_{lang}.po 译文漂移: {wrong[:5]}"


def test_template_placeholders_match():
  """中文模板与英文 msgid 模板的占位符数量必须一致，否则数值代不回去。"""
  for zh, en in TPL_MAP.items():
    assert len(re.findall(r"\{[^}]*\}", zh)) == len(re.findall(r"\{[^}]*\}", en)), (zh, en)
  assert len(CONST_MAP) > 150 and len(TPL_MAP) >= 20


def test_zh_chs_static_alerts_are_byte_identical(restore_language):
  """中文设备上的静态 alert 与迁移前逐字相同。"""
  restore_language.reload("zh-CHS")
  for zh, en in list(CONST_MAP.items())[:40]:
    assert restore_language.tr(en) == zh, (en, zh, restore_language.tr(en))
  # 几个高频/高风险文案单独点名
  for en, zh in [
    ("Camera Malfunction", "摄像头故障"),
    ("TAKE CONTROL IMMEDIATELY", "立即接管控制"),
    ("WARNING: This branch is not tested", "警告：此分支未经测试"),
    ("km/h", "公里/时"),
    ("mph", "英里/时"),
    ("Relaxed", "舒适"),
  ]:
    assert restore_language.tr(en) == zh


def test_zh_chs_dynamic_alerts_use_template_fallback(restore_language):
  """数值已拼进字符串时，tr() 仍能按 po 模板把数值代回中文。"""
  restore_language.reload("zh-CHS")
  cases = [
    ("Drive above 30 km/h to engage", "请将时速提高至 30 km/h 来启用"),
    ("Steer Unavailable Below 20 mph", "转向在 20 mph 以下不可用"),
    ("Used: 85%", "已用 85%"),
    ("Frames Dropped: 2.4%", "已丢帧 2.4%"),
    ("Calibration in Progress: 50%", "校准进行中：50%"),
    ("Press + to Set\n45 mph", "按 + 键调至\n45 mph"),
    ("Adjusting to Speed Limit\n45 mph", "正在调整至限速\n45 mph"),
  ]
  for en, zh in cases:
    assert restore_language.tr(en) == zh, (en, zh, restore_language.tr(en))


def test_english_falls_back_to_msgid(restore_language):
  """切到英文时显示英文 msgid，不再被锁死在中文。"""
  restore_language.reload("en")
  for en, _ in list(CONST_MAP.items())[:20]:
    assert restore_language.tr(en) == en
  assert restore_language.tr("Drive above 30 km/h to engage") == "Drive above 30 km/h to engage"


def test_language_switch_rebuilds_template_index(restore_language):
  """语言切换后模板索引/缓存必须重建，不能拿旧语言译文响应新语言。"""
  restore_language.reload("zh-CHS")
  assert restore_language.tr("Used: 85%") == "已用 85%"
  restore_language.reload("en")
  assert restore_language.tr("Used: 85%") == "Used: 85%"
  restore_language.reload("zh-CHS")
  assert restore_language.tr("Used: 85%") == "已用 85%"
