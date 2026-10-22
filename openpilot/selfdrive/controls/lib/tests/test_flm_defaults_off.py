"""FLM ships off: the analyzer and its runtime injection must not touch this car
until the user opts in.

The keys below are compiled into libparams_c.so (see
ai/docs/libparams_c_rebuild_recipe_20261021.md). On a device with a stale
shared library the read raises UnknownKeyName, which is a real drift signal, so
it is not swallowed here: the test skips only when the library is missing
entirely (PC / CI without a checkout build).
"""

import pytest

try:
  from openpilot.common.params import Params
  Params()  # triggers the ctypes load; raises if libparams_c is absent
  LPARAMS_AVAILABLE = True
except Exception:
  LPARAMS_AVAILABLE = False


@pytest.mark.skipif(not LPARAMS_AVAILABLE, reason="libparams_c not built in this checkout")
def test_flm_is_off_by_default():
  params = Params()
  # The master switch and the injection gate are separate on purpose: the
  # analyzer may be enabled offline while the controller still runs stock
  # friction. Both default off.
  assert not params.get_bool("AdvancedLateralTune")
  assert not params.get_bool("FlmRuntimeOverridesEnabled")
  # Unset bundle means latcontrol_torque calls set_flm_runtime_overrides({}),
  # so FRICTION_THRESHOLD stays in charge of the friction term.
  raw = params.get("FLMActiveOverrides")
  assert not (raw or b"")
