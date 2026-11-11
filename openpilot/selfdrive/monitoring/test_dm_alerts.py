from types import SimpleNamespace


from openpilot.cereal import log
from openpilot.selfdrive.monitoring.dm_alerts import driver_monitoring_hud_alert
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized



class TestDmAlertsTests(OpenpilotTestCase):

  @parameterized.expand([(False, False, 'none', 0), (True, False, 'none', 0), (False, True, 'none', 0), (True, True, 'none', 0), (False, False, 'one', 1), (True, False, 'one', 1), (False, True, 'one', 1), (True, True, 'one', 1), (False, False, 'two', 2), (True, False, 'two', 2), (False, True, 'two', 2), (True, True, 'two', 2), (False, False, 'three', 3), (True, False, 'three', 3), (False, True, 'three', 3), (True, True, 'three', 3)], names=('invalid', 'disabled', 'level', 'expected'))  # noqa: E501
  def test_hud_level_requires_fresh_enabled_monitoring(self, level, expected, invalid, disabled):
    class Messages(dict):
      def all_checks(self, services):
        assert services == ['driverMonitoringState']
        return not invalid

    state = log.DriverMonitoringState.new_message(alertLevel=level, dm2Disabled=disabled)
    assert driver_monitoring_hud_alert(Messages(driverMonitoringState=state)) == (0 if invalid or disabled else expected)


  def test_unknown_dm_alert_is_not_exported(self):
    sm = {'driverMonitoringState': SimpleNamespace(alertLevel='unknown', dm2Disabled=False)}
    class Messages(dict):
      def all_checks(self, services):
        return True
    assert driver_monitoring_hud_alert(Messages(sm)) == 0
