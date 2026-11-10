from pathlib import Path

from openpilot.sunnypilot.carrot.tools.ui_control_extractor import (
  extract_page_controls,
  po_translations,
)
import unittest

from openpilot.common.test import OpenpilotTestCase
SETTINGS_DIR = Path(__file__).resolve().parents[3] / "selfdrive" / "ui" / "sunnypilot" / "layouts" / "settings"


def _extract():
  return extract_page_controls(SETTINGS_DIR)














class TestUiControlExtractor(unittest.TestCase):
  def test_extracts_titles_for_the_real_pages(self):
    controls = _extract()
    # dict shorthand (visuals), direct toggle (toyota brand sub-layout), option slider
    assert controls["SignalYoloEnabled"]["title"] == "Traffic Light Vision Boxes (YOLO)"
    assert controls["ToyotaTSS2Smooth"]["title"] == "TSS2 Smooth Longitudinal (Alpha)"
    assert controls["AutoGasSyncSpeed"]["min"] == 0 and controls["AutoGasSyncSpeed"]["max"] == 200

  def test_descriptions_are_plain_text(self):
    controls = _extract()
    descr = controls["SignalYoloEnabled"]["descr"]
    assert descr.startswith("Run the YOLOv8 traffic-light detector")
    assert "<" not in descr and "  " not in descr

  def test_multiple_button_labels_carry_order(self):
    controls = _extract()
    assert controls["ShowRadarInfo"]["buttons"] == ["Off", "Speed Only", "Speed + Distance", "Full"]
    assert controls["ChevronInfo"]["buttons"][0] == "Off"

  def test_callback_bound_toggles_resolve_their_key(self):
    controls = _extract()
    # the toyota pages never pass param=; the key only appears in the callbacks
    assert controls["ToyotaDriveMode"]["title"]
    assert "drive-mode button" in controls["ToyotaDriveMode"]["descr"].lower()

  def test_tr_noop_dict_descriptions_resolve(self):
    controls = _extract()
    assert "Factory Toyota longitudinal control" in controls["ToyotaEnforceStockLongitudinal"]["descr"]


class TestUiControlExtractorAdditional(OpenpilotTestCase):
  def test_po_translations_lookup(tmp_path):
    po = tmp_path / "t.po"
    lines = [
      'msgid ""',
      'msgstr ""',
      '"Content-Type: text/plain; charset=UTF-8\\n"',
      '',
      '#, fuzzy',
      'msgid "Fuzzy Line"',
      'msgstr "已废弃"',
      '',
      'msgid "Off"',
      'msgstr "关"',
      '',
      'msgid "Multi "',
      '"Line"',
      'msgstr "多 "',
      '"行"',
      '',
    ]
    po.write_text("\n".join(lines), encoding="utf-8")
    got = po_translations(po)
    assert got["Off"] == "关"
    assert "Fuzzy Line" not in got
    assert got["Multi Line"] == "多 行"
