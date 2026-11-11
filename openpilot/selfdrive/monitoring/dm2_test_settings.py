"""Test-only VISION policy for the DM2 timing suites.

The DM2 tests were authored against carrotpilot's VISION alert timeouts
(5, 8, 13 s). This fork ships the regulatory defaults (8, 12, 20 s) in
policy.py, whose header explicitly forbids fork maintainers from changing
those numbers. With the shipped values every camera-timing assertion fires
about 1.6x too early, which makes the DM2 state machine look broken even
though it is correct.

So the suites pin their *own* settings object to the values they specify.
Nothing here touches the running driver monitor: the patch is scoped to a
single test via addCleanup().
"""

from unittest import mock

from openpilot.selfdrive.monitoring import policy


class CarrotVisionSettings(policy.DRIVER_MONITOR_SETTINGS):
  def __init__(self):
    super().__init__()
    self._VISION_POLICY_ALERT_1_TIMEOUT = 5.
    self._VISION_POLICY_ALERT_2_TIMEOUT = 8.
    self._VISION_POLICY_ALERT_3_TIMEOUT = 13.


def pin_carrot_vision_settings(test_case):
  """Use the suite's declared VISION timeouts for one test only."""
  patcher = mock.patch.object(policy, 'DRIVER_MONITOR_SETTINGS', CarrotVisionSettings)
  patcher.start()
  test_case.addCleanup(patcher.stop)
