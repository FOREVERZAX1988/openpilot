"""Exercise boot migration with the native typed Params implementation."""

from openpilot.selfdrive.monitoring.config import configure_monitoring
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized



class TestConfigParamsTests(OpenpilotTestCase):

  @parameterized.expand([None, 0, 1, 2], names=('legacy',))
  def test_boot_configuration_with_native_params(self, tmp_path, legacy):
    try:
      from openpilot.common.params_pyx import Params as NativeParams
    except ImportError:
      self.skipTest('openpilot.common.params_pyx unavailable on this host')
    params = NativeParams(str(tmp_path / 'params'))
    if legacy is not None:
      params.put_int('DisableDM', legacy)
    env = {}
    configure_monitoring(params, env)
    assert type(params.get('DriverMonitoringMode')) is int
    assert params.get('DriverMonitoringMode') == 0
    assert params.get('CarrotVisionEnabled') is (legacy == 2)
    assert 'CARROT_DM_MODE' not in env
    params.put_int('DriverMonitoringMode', 1)
    params.put_bool('CarrotVisionEnabled', False)
    configure_monitoring(params, env)
    assert 'CARROT_DM_MODE' not in env
    assert params.get('CarrotVisionEnabled') is False
