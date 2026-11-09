#!/usr/bin/env python3
from __future__ import annotations
"""Unit tests for the CarrotServ one-shot ATC legacy migration.

Devices that ran carrot before AutoTurnControl was default-on carry config.py's
old seeded 0 (ATC fully off). The first-enable seeding block cannot fix them:
CarrotNavFeaturesSeeded is already set, so it never re-fires. CarrotServ bumps a
stored 0 to full ATC (2) exactly once under CarrotAtcMigrated; any explicit user
choice made afterwards - including 0 via the tuning UI - must win forever.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

try:
  from openpilot.common.params import Params
except (OSError, ModuleNotFoundError):
  from openpilot.common.tests import params_pc_stub
  params_pc_stub.register()
  Params = params_pc_stub.Params

# Windows/PC: openpilot.common.realtime pulls hardware -> gpio -> fcntl. Stub it
# out for the import, then restore - a leftover stub in sys.modules replaces
# "openpilot.common" with a non-package object and breaks later test modules in
# the same process (same guard as test_carrot_controls.py).
_SAVED_MODULES = {name: sys.modules.get(name) for name in (
  "openpilot.common", "openpilot.common.realtime", "openpilot.common.swaglog",
)}
try:
  _common_pkg = sys.modules.get("openpilot.common") or types.ModuleType("openpilot.common")
  _realtime = types.ModuleType("openpilot.common.realtime")
  _realtime.DT_MDL = 0.05
  _swaglog = types.ModuleType("openpilot.common.swaglog")
  _swaglog.cloudlog = MagicMock()
  sys.modules["openpilot.common"] = _common_pkg
  sys.modules["openpilot.common.realtime"] = _realtime
  sys.modules["openpilot.common.swaglog"] = _swaglog

  from openpilot.sunnypilot.carrot.carrot_serv import CarrotServ
  from openpilot.sunnypilot.carrot.config import UnifiedParams
finally:
  for _name, _module in _SAVED_MODULES.items():
    if _module is None:
      sys.modules.pop(_name, None)
    else:
      sys.modules[_name] = _module


def _fresh_unified_params() -> UnifiedParams:
  """Rebuild the UnifiedParams singleton against a clean Params store.

  UnifiedParams is a singleton, so every scenario resets both it and the store;
  the nonexistent json path keeps _nav_data at compile-time defaults only.
  """
  if hasattr(Params, "_reset"):
    Params._reset()
  UnifiedParams._instance = None
  UnifiedParams._initialized = False
  return UnifiedParams(nav_json_file="/nonexistent/carrot_nav_params.json")


class TestCarrotAtcMigration(unittest.TestCase):
  def setUp(self) -> None:
    self.params = _fresh_unified_params()
    self.serv = CarrotServ(params=self.params)

  def test_legacy_seeded_zero_is_bumped_once(self):
    # The 192.168.7.229 device state: carrot enabled, nav flag already set,
    # AutoTurnControl stuck at config.py's old default.
    self.params.put_bool("CarrotEnabled", True)
    self.params.put_bool("CarrotNavFeaturesSeeded", True)
    self.params.put_int("AutoTurnControl", 0)

    self.serv.update_params()

    self.assertEqual(self.params.get_int("AutoTurnControl"), 2)
    self.assertTrue(self.params.get_bool("CarrotAtcMigrated"))

  def test_migration_runs_exactly_once(self):
    self.params.put_bool("CarrotEnabled", True)
    self.params.put_bool("CarrotNavFeaturesSeeded", True)
    self.params.put_int("AutoTurnControl", 0)
    self.serv.update_params()

    # The user turns ATC off explicitly after the migration; it must stick.
    self.params.put_int("AutoTurnControl", 0)
    self.serv.update_params()

    self.assertEqual(self.params.get_int("AutoTurnControl"), 0)
    self.assertTrue(self.params.get_bool("CarrotAtcMigrated"))

  def test_explicit_nonzero_choice_is_respected(self):
    self.params.put_bool("CarrotEnabled", True)
    self.params.put_bool("CarrotNavFeaturesSeeded", True)
    self.params.put_int("AutoTurnControl", 3)  # decel-only, a deliberate choice

    self.serv.update_params()

    self.assertEqual(self.params.get_int("AutoTurnControl"), 3)
    self.assertTrue(self.params.get_bool("CarrotAtcMigrated"))

  def test_missing_key_gets_full_atc(self):
    self.params.put_bool("CarrotEnabled", True)

    self.serv.update_params()

    self.assertEqual(self.params.get_int("AutoTurnControl"), 2)
    self.assertTrue(self.params.get_bool("CarrotAtcMigrated"))

  def test_carrot_disabled_leaves_device_alone(self):
    self.params.put_bool("CarrotEnabled", False)
    self.params.put_int("AutoTurnControl", 0)

    self.serv.update_params()

    self.assertEqual(self.params.get_int("AutoTurnControl"), 0)
    self.assertFalse(self.params.get_bool("CarrotAtcMigrated"))


if __name__ == "__main__":
  unittest.main()
