"""A parameter's declared type, its default and its stored value have to agree.

DynamicTFollowLC was flipped FLOAT -> INT so its settings row could save at all
(an int-only control writing into a FLOAT key raises TypeMismatch). The row was
fixed, the static checks went green - and the car still had the old value on
disk: /data/params/d/DynamicTFollowLC contained "100.0". Params cannot cast that
to INT, so every reader that goes to the raw store saw 0, which for this key is
a lane-change gap credit of 0.00 instead of 1.00, and the only trace is a log
line:

    Failed to cast param DynamicTFollowLC with value=b'100.0' from type INT

Two things follow. A type change needs a stored-value migration, and deleting
the key is not that migration: Params.get_int(key) falls back to its own 0
default, not to the compiled-in default, so removing "100.0" turns 0 into 0.
(carrot's UnifiedParams does consult config.py's table, which is why the planner
kept the right value while raw-store readers did not.)

Three guards, all cheap and all runnable offroad:

  1. a declared INT carries an integer literal default (catches a type flip that
     forgets the default),
  2. the fork's own default table uses the type the key declares,
  3. on a device, every stored value parses as its declared type (catches the
     stale value itself, the check that was missing).

Plain unittest over text files and /data/params; the device-only class skips
itself when there is no param store, so this runs on a PC too.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from openpilot.sunnypilot.carrot.tests.audit_param_consistency import (
  parse_config_py,
  parse_param_types,
  parse_params_keys,
)

PARAMS_DIR = Path("/data/params/d")
INT_LITERAL = re.compile(r"[+-]?\d+$")
FLOAT_LITERAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
BOOL_LITERALS = {"0", "1", "true", "false", "True", "False"}

REMEDY = "rewrite the value as the declared default; removing the key is not enough - Params.get_int falls back to 0, not to the compiled-in default"


def parses_as(value: str, declared: str) -> bool:
  """True if `value` (as stored on disk) can be cast to `declared`."""
  value = value.strip()
  if declared == "INT":
    return bool(INT_LITERAL.match(value))
  if declared == "FLOAT":
    return bool(FLOAT_LITERAL.match(value))
  if declared == "BOOL":
    return value in BOOL_LITERALS
  return True  # STRING / JSON / BYTES accept any bytes


def python_type_matches(value: object, declared: str) -> bool:
  """True if a config.py default of this Python type can be written to `declared`.

  A BOOL key written from Python as 0/1 is fine (Params casts int -> BOOL, and
  config.py stores the fork's 229 imported knobs that way); the reverse, a float
  or a string where an int belongs, is what this catches.
  """
  if declared == "BOOL":
    return isinstance(value, bool) or (isinstance(value, int) and value in (0, 1))
  if declared == "INT":
    return isinstance(value, int) and not isinstance(value, bool)
  if declared == "FLOAT":
    return isinstance(value, (int, float)) and not isinstance(value, bool)
  if declared == "STRING":
    return isinstance(value, str)
  return True


class TestDeclaredTypes(unittest.TestCase):
  def test_the_tables_still_parse(self) -> None:
    """A silent parser would make every assertion below vacuous."""
    self.assertGreater(len(parse_param_types()), 500, "no declared types parsed from params_keys.h")
    self.assertGreater(len(parse_params_keys()), 500, "no defaults parsed from params_keys.h")
    self.assertGreater(len(parse_config_py()), 100, "no defaults parsed from carrot/config.py")

  def test_an_int_parameter_declares_an_integer_default(self) -> None:
    """An INT key whose default is written as "0.0" cannot be read at all.

    An empty default is allowed: keys like AthenadPid and BootCount are INT and
    deliberately start unset.
    """
    types = parse_param_types()
    defaults = parse_params_keys()
    offenders = []
    for key, declared in sorted(types.items()):
      if declared != "INT":
        continue
      default = defaults.get(key, "")
      if default != "" and not INT_LITERAL.match(default):
        offenders.append(f"{key}: declares INT, default is {default!r}")
    self.assertFalse(offenders, "INT parameters with a non-integer default:\n  " + "\n  ".join(offenders))

  def test_the_fork_default_table_uses_the_declared_type(self) -> None:
    """config.py's `_DEFAULT_NAV_PARAMS` is what UnifiedParams falls back to.

    A float there for an INT key means the fallback cannot be written back, and
    the value the car uses is not the value the settings row would save.
    """
    types = parse_param_types()
    offenders = []
    for key, value in sorted(parse_config_py().items()):
      declared = types.get(key)
      if declared is None:
        continue  # webui-only or not-yet-registered knob: the audit owns that claim
      if not python_type_matches(value, declared):
        offenders.append(f"{key}: declares {declared}, config.py defaults to {value!r}")
    self.assertFalse(offenders, "carrot default table disagrees with the declared type:\n  " + "\n  ".join(offenders))


@unittest.skipUnless(PARAMS_DIR.is_dir(), "no /data/params on this machine - device-only check")
class TestStoredValuesParse(unittest.TestCase):
  def test_every_stored_value_parses_as_its_declared_type(self) -> None:
    """The check that would have caught DynamicTFollowLC's stale "100.0"."""
    types = parse_param_types()
    offenders = []
    for path in sorted(PARAMS_DIR.iterdir()):
      declared = types.get(path.name)
      if declared is None or not path.is_file():
        continue
      try:
        value = path.read_text(encoding="utf-8", errors="replace")
      except OSError:
        continue
      if not parses_as(value, declared):
        offenders.append(f"{path.name}: declares {declared}, stores {value!r}")
    message = f"stored value does not parse as its declared type - {REMEDY}:\n  "
    self.assertFalse(offenders, message + "\n  ".join(offenders))


if __name__ == "__main__":
  unittest.main()
