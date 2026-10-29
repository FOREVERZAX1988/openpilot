"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
"""Tests for the carrot web panel's settings pages (port 8088).

The panel reads the on-device settings sources and the params binary's own key list, and
never renders a key the binary does not declare. Two things are easy to get quietly wrong
and are what these tests pin down:

- `Params.all_keys()` hands its keys back as *bytes* (the binary's own buffer), while the
  page scan produces `str`. Compared as they come, nothing matches and every key falls into
  the "other" group, whose rows then fail to render at all; the keys are decoded before use.
- a form can carry any name at all, so a key that is not declared must be dropped rather
  than written.
"""
import unittest
from unittest import mock

from openpilot.sunnypilot.carrot import web_settings as ws


def _as_str(key):
  return key.decode() if isinstance(key, (bytes, bytearray)) else str(key)


class _FakeParams:
  """Mirrors the slice of `Params` web_settings uses; all_keys() hands back bytes."""

  def __init__(self, keys, types=None, store=None):
    self.keys = list(keys)
    self.types = dict(types or {})
    self.store = dict(store or {})

  def all_keys(self):
    return [k.encode() for k in self.keys]

  def get_type(self, key):
    return self.types.get(_as_str(key), ws.T_STRING)

  def get(self, key):
    return self.store.get(_as_str(key))


class TestCollect(unittest.TestCase):
  def test_bytes_keys_from_the_binary_still_group_by_page(self):
    scanned = ws.scan_ui_pages(ws.ui_settings_dir())
    declared = sorted({k for keys in scanned.values() for k in keys} | {"NotOnAnyPage"})
    grouped, kinds, values = ws.collect(_FakeParams(declared, dict.fromkeys(declared, ws.T_INT)))

    # the regression: keys handed back as bytes must not empty the pages out
    self.assertIn("cruise", grouped)
    self.assertIn("other", grouped)
    # nothing rendered is a bytes literal, and every one of them is declared
    for key in (k for keys in grouped.values() for k in keys):
      self.assertIsInstance(key, str)
      self.assertIn(key, kinds)
    self.assertTrue(all(isinstance(k, str) for k in kinds))


class TestGrouping(unittest.TestCase):
  def test_undeclared_keys_fall_out_of_the_page_grouping(self):
    self.assertEqual(ws.group_keys({"cruise": ["Known", "Unknown"]}, ["Known"]), {"cruise": ["Known"]})

  def test_a_page_that_names_nothing_declared_disappears(self):
    self.assertEqual(ws.group_keys({"pairing": ["Scan", "Retry"]}, ["Known"]), {"other": ["Known"]})


class TestOnDeviceScan(unittest.TestCase):
  def test_the_on_device_pages_are_found(self):
    pages = ws.scan_ui_pages(ws.ui_settings_dir())
    self.assertGreater(len(pages), 5)
    self.assertIn("cruise", pages)
    self.assertIn("CustomAccShortPressIncrement", pages["cruise"])

  def test_a_key_quoted_either_way_is_found(self):
    """The scanner reads source text, so both quote styles have to count.

    `carrot_tuning_items.py` (Carrot Tuning + the Developer page) writes every key as
    `param='X'`; every other page writes `param="X"`. A regex that only matched `"` made
    the panel group 150 of the 294 declared keys the pages name, with no error anywhere:
    the missing ones simply never appeared, and the (then empty) Carrot Tuning section
    looked like a page that has no settings. Pinned directly so a future rewrite of the
    scanner has to keep both.
    """
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
      page = Path(tmp) / "somepage.py"
      source = "\n".join([
        "toggle_item_sp(title=tr('A'), param='SingleQuoted')",
        'toggle_item_sp(title=tr("B"), param="DoubleQuoted")',
        'toggle_item_sp(title=tr("C"), param="MixedQuotes")',
      ])
      page.write_text(source, encoding="utf-8")
      keys = set(ws.scan_ui_pages(tmp).get("somepage", []))
    self.assertIn("SingleQuoted", keys)
    self.assertIn("DoubleQuoted", keys)
    self.assertIn("MixedQuotes", keys)

  def test_no_declared_key_the_pages_name_is_lost(self):
    """The end-to-end version: grouping must not drop a key a page actually names.

    Counted against `params_keys.h` rather than a hardcoded number, so adding a page row
    cannot make this pass by accident, and removing the quote handling cannot make it
    pass quietly.
    """
    from openpilot.sunnypilot.carrot.tests.audit_param_consistency import parse_params_keys
    declared = set(parse_params_keys())
    root = ws.ui_settings_dir()
    scanned = {k for keys in ws.scan_ui_pages(root).values() for k in keys}
    self.assertGreaterEqual(len(scanned & declared), 280,
                            "the page scan lost keys again - check _KEYWORD_ARG_RE handles both quote styles")
    # the Carrot Tuning page is the one that quotes with ', so it is the canary
    self.assertIn("VisionSpeedLimitLowLimitThreshold", scanned)
    self.assertIn("CarrotLeadPreviewEnabled", scanned)


class TestRender(unittest.TestCase):
  def test_every_declared_type_renders(self):
    for kind in (ws.T_STRING, ws.T_BOOL, ws.T_INT, ws.T_FLOAT, ws.T_TIME, ws.T_JSON, ws.T_BYTES):
      html = ws.render_control("SomeKey", kind, None)
      self.assertIn("SomeKey", html)
      self.assertIn('name="p[SomeKey]"', html)

  def test_page_and_index_render(self):
    grouped = {"cruise": ["SomeKey"]}
    kinds = {"SomeKey": ws.T_INT}
    page = ws.render_page("cruise", grouped["cruise"], kinds, {"SomeKey": 3})
    self.assertIn("SomeKey", page)
    self.assertIn("cruise", ws.render_index(grouped))

  def test_form_updates_are_limited_to_declared_keys(self):
    kinds = {"SomeKey": ws.T_INT}
    self.assertEqual(ws.parse_form_updates({"p[SomeKey]": ["7"]}, kinds), {"SomeKey": "7"})
    self.assertEqual(ws.parse_form_updates({"p[NotDeclared]": ["7"]}, kinds), {})
    self.assertEqual(ws.parse_form_updates({"SomeKey": ["7"]}, kinds), {})


class _PanelParams:
  """Params stand-in for apply_updates: the binary's string-shaped store."""

  def __init__(self, values=None):
    self.values = dict(values or {})
    self.puts = []

  def get(self, key, block=False, return_default=False):
    return self.values.get(key)

  def get_bool(self, key, block=False):
    return str(self.values.get(key, "0")) in ("1", "True", "true")

  def put(self, key, value, block=False):
    self.puts.append((key, value))
    self.values[key] = "1" if value is True else "0" if value is False else str(value)

  def put_bool(self, key, value, block=False):
    self.put(key, bool(value), block=block)


def _offroad_panel(**values) -> _PanelParams:
  return _PanelParams({"IsOnroad": "0", "IsOffroad": "1", **values})


class TestApplyUpdatesUsesTheOneWriter(unittest.TestCase):
  """The panel is a second writer, and it must not be a second set of rules.

  Writing ExperimentalMode raw from the browser set the switch while the confirmation bit
  stayed clear, so the mode never actually ran (`experimental_mode_requested()` answered no)
  -- and after the next reboot selfdrived deleted the switch. The panel now goes through the
  same state machine the companion API uses, and a refused transition is reported instead
  of stored.
  """

  def setUp(self):
    recorder = mock.patch.object(ws, "_record_change")
    self.recorded = recorder.start()
    self.addCleanup(recorder.stop)

  def test_enabling_experimental_mode_also_arms_the_confirmation_bit(self):
    params = _offroad_panel()
    written, skipped = ws.apply_updates(params, {ws.MODE_ON_PARAM: "1"},
                                        {ws.MODE_ON_PARAM: ws.T_BOOL})

    self.assertEqual((written, skipped), (1, 0))
    self.assertEqual(params.values[ws.MODE_ON_PARAM], "1")
    self.assertEqual(params.values["ExperimentalModeConfirmed"], "1")

    from openpilot.sunnypilot.common.mode_state_runtime import experimental_mode_requested
    self.assertTrue(experimental_mode_requested(params))
    self.recorded.assert_called_once()

  def test_an_unknown_road_state_is_skipped_not_stored(self):
    # nothing wrote IsOnroad/IsOffroad: a mode change on a half-known road state is a guess
    params = _PanelParams()
    written, skipped = ws.apply_updates(params, {ws.MODE_ON_PARAM: "1"},
                                        {ws.MODE_ON_PARAM: ws.T_BOOL})

    self.assertEqual((written, skipped), (0, 1))
    self.assertNotIn(ws.MODE_ON_PARAM, params.values)
    self.recorded.assert_not_called()

  def test_safe_mode_holds_the_switch(self):
    params = _offroad_panel(SafeMode="1")
    written, skipped = ws.apply_updates(params, {ws.MODE_ON_PARAM: "1"},
                                        {ws.MODE_ON_PARAM: ws.T_BOOL})

    self.assertEqual((written, skipped), (0, 1))
    self.assertNotIn(ws.MODE_ON_PARAM, params.values)

  def test_disabling_never_touches_the_confirmation_bit(self):
    params = _offroad_panel(**{ws.MODE_ON_PARAM: "1", "ExperimentalModeConfirmed": "1"})
    written, _ = ws.apply_updates(params, {ws.MODE_ON_PARAM: "0"}, {ws.MODE_ON_PARAM: ws.T_BOOL})

    self.assertEqual(written, 1)
    self.assertEqual(params.values[ws.MODE_ON_PARAM], "0")
    self.assertEqual(params.values["ExperimentalModeConfirmed"], "1")

  def test_plain_values_still_write_through_the_declared_type(self):
    params = _offroad_panel()
    written, skipped = ws.apply_updates(params, {"IsMetric": "1", "SomeInt": "not-a-number"},
                                        {"IsMetric": ws.T_BOOL, "SomeInt": ws.T_INT})

    self.assertEqual((written, skipped), (1, 1))
    self.assertEqual(params.values["IsMetric"], "1")
    self.assertNotIn("SomeInt", params.values)
    self.recorded.assert_called_once()


if __name__ == "__main__":
  unittest.main()
