"""Safe Mode against the real Params library, in a throwaway store.

test_safe_mode.py drives a `Params` double, and a double accepts a string for a BOOL
key. The real store does not: `Params.put` is strictly typed and raises TypeError for
a str written to a BOOL/INT/FLOAT/JSON key. Four mismatches in the runtime layer were
invisible until it was run against the library, and all four were silent because every
write is wrapped in try/except:

  * the string targets from safe_mode.py were written straight through, so nothing was
    ever forced — _put swallowed the TypeError;
  * `get(key, return_default=True)` returns the *stored* value once the key is set, so
    the "fall back to the registered default" branch handed safe_value the value it was
    supposed to replace;
  * the JSON backup came back through `str(dict)` (Python repr, not JSON), parsed as
    "no backup", and made every restore a no-op;
  * a BOOL read back as "False" never equaled the target "0", so every enforce cycle
    rewrote all the BOOL keys.

These tests run the real thing end to end. The store is a temp directory, so nothing
here touches the car's parameters.
"""
import pytest

from openpilot.common.params import Params, lib
from openpilot.sunnypilot.common.safe_mode_runtime import (
  apply_safe_mode,
  backup_document,
  enforce_safe_mode,
  restore_safe_mode,
)

pytestmark = pytest.mark.skipif(lib is None, reason="params native library not available")


@pytest.fixture
def store(tmp_path):
  return Params(str(tmp_path / "params"))


def test_apply_forces_the_knobs_and_records_them(store):
  store.put("SteerRatio", 1.53, block=True)
  store.put("CustomSR", 1, block=True)
  store.put_bool("LaneCenteringEnabled", True, block=True)

  assert apply_safe_mode(store)

  assert store.get("SteerRatio") == pytest.approx(0.0)
  assert store.get("CustomSR") == 0
  assert store.get("LaneCenteringEnabled") is False
  backup = backup_document(store)
  assert backup["SteerRatio"] == {"present": True, "value": "1.53"}
  assert backup["CustomSR"] == {"present": True, "value": "1"}


def test_reapply_is_idempotent(store):
  assert apply_safe_mode(store)
  # This runs every SAFE_MODE_ENFORCE_FRAMES frames in the control loop; a False here
  # is what keeps it from rewriting every BOOL key five times a second.
  assert apply_safe_mode(store, ensure_backup=False) is False


def test_restore_puts_the_old_values_back(store):
  store.put("SteerRatio", 1.53, block=True)
  store.put_bool("LaneCenteringEnabled", True, block=True)
  store.put_bool("IsOffroad", True, block=True)
  apply_safe_mode(store)

  assert restore_safe_mode(store)

  assert store.get("SteerRatio") == pytest.approx(1.53)
  assert store.get("LaneCenteringEnabled") is True
  assert backup_document(store) == {}


def test_restore_is_refused_while_the_car_is_moving(store):
  store.put("SteerRatio", 1.53, block=True)
  apply_safe_mode(store)
  store.put_bool("IsOnroad", True, block=True)

  assert restore_safe_mode(store) is False
  assert store.get("SteerRatio") == pytest.approx(0.0)


def test_enforce_is_a_noop_with_the_switch_off(store):
  store.put("SteerRatio", 1.53, block=True)

  assert enforce_safe_mode(store, 0) is False
  assert store.get("SteerRatio") == pytest.approx(1.53)
