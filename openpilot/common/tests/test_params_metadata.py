"""The parameter metadata Safe Mode needs must exist in the real library.

The Safe Mode Python layer swallows every metadata error on purpose: a device whose
`libparams_c.so` predates the metadata must leave the parameter alone instead of
taking down the control loop. The cost is that a stale library looks exactly like
"no stock value registered" — Safe Mode silently does nothing and the Python tests
stay green, because they drive a `Params` double (see test_safe_mode.py).

These tests read the real library, so a library that is older than the metadata
fails here instead of driving silently. `params_keys.h` is a compile-time table baked
into `libparams_c.so`, so a key or a binding added to the headers is invisible until
the library is rebuilt: ai/docs/libparams_c_rebuild_recipe_20261021.md.
"""
import pytest

from openpilot.common.params import Params, lib
from openpilot.sunnypilot.common.safe_mode import (
  SAFE_MODE_BACKUP_PARAM,
  SAFE_MODE_MANAGED_KEYS,
  SAFE_MODE_PARAM,
)

pytestmark = pytest.mark.skipif(lib is None, reason="params native library not available")

# The three C bindings upstream 5ee2c9f618 added for the metadata. Renaming any of
# them here without renaming it in the C library must fail loudly.
REQUIRED_BINDINGS = ("params_get_stock", "params_get_tuning_level", "params_get_settings_tier")


def test_metadata_bindings_are_exported():
  missing = [name for name in REQUIRED_BINDINGS if not hasattr(lib, name)]
  hint = "Rebuild it per ai/docs/libparams_c_rebuild_recipe_20261021.md"
  assert not missing, f"{missing} missing from libparams_c.so: the library predates the metadata. {hint}"


# Managed keys whose feature we have not ported yet. The managed list is kept verbatim
# with upstream so future pulls of it apply cleanly, and safe_mode_runtime skips a key
# the store does not know instead of acting on it. Registry entries (ai/docs/
# upstream_divergence_registry.json): NNFFMode -> 63a6f3211b, VisionSpeedLimit* ->
# d81eec5899, both still `eval`.
UNPORTED_MANAGED_KEYS = frozenset({"NNFFMode", "VisionSpeedLimitEnabled", "VisionSpeedLimitLowLimitFilter"})


def _registered_keys() -> set[str]:
  """The keys this library knows, without raising on a key that is absent.

  `Params.check_key` raises UnknownKeyName, and it has to: a caller that reads an
  unregistered key is always a mistake. Here the absence is the thing under test.
  """
  return {key.decode() for key in Params().all_keys()}


def test_safe_mode_keys_are_registered():
  known = _registered_keys()
  assert SAFE_MODE_PARAM in known
  assert SAFE_MODE_BACKUP_PARAM in known
  # A copied managed list from another fork names keys that are not registered here,
  # and every read of those raises; only the known-unported ones may be absent.
  unknown = set(SAFE_MODE_MANAGED_KEYS) - known - UNPORTED_MANAGED_KEYS
  assert not unknown, f"Safe Mode manages keys this build does not register: {sorted(unknown)}"


def test_unported_managed_keys_are_still_unported():
  # The other direction: once a feature lands, its key becomes registered and this set
  # has to shrink, otherwise the entry rots into a silent exemption.
  missing = UNPORTED_MANAGED_KEYS - _registered_keys()
  ported = sorted(set(UNPORTED_MANAGED_KEYS) - missing)
  hint = "the feature was ported; drop it from UNPORTED_MANAGED_KEYS"
  assert missing == set(UNPORTED_MANAGED_KEYS), f"{ported} is now registered: {hint}"


def test_stock_value_falls_back_to_the_default():
  params = Params()
  for key in ("SteerRatio", "SteerDelay", "SteerFriction", "SteerKP", "SteerLatAccel"):
    stock = params.get_stock_value(key)
    assert stock is not None, key
    assert isinstance(stock, bytes), key
  # The Steer*Stock keys are registered as 0.0 = "not known" so that Safe Mode leaves
  # them alone rather than writing a wrong number; the binding must still resolve them.
  assert params.get_stock_value("SteerRatioStock") is not None


def test_a_missing_binding_degrades_instead_of_breaking_the_import():
  # Bindings are resolved when openpilot.common.params is imported. A device whose
  # library predates the metadata must keep every daemon that imports Params alive, so
  # the three new bindings are optional and answer "not known"; the test above is what
  # reports the stale library. Hard-binding them here would turn a stale .so into a
  # fork-wide import failure.
  from openpilot.common.params import _bind_optional
  assert _bind_optional("params_definitely_not_a_symbol", [], None) is None


def test_tuning_metadata_is_readable():
  params = Params()
  assert params.get_tuning_level("SteerRatio") == 0
  assert params.get_settings_tier("SteerRatio") == 1
