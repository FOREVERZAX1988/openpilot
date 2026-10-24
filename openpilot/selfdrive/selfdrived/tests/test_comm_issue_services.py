from openpilot.cereal.services import SERVICE_LIST
from openpilot.selfdrive.selfdrived.selfdrived import comm_issue_checked_services


class _FakeSubMaster:
  def __init__(self, static_freq_services, ignore_valid=(), ignore_alive=(), ignore_average_freq=()):
    self.static_freq_services = set(static_freq_services)
    self.ignore_valid = list(ignore_valid)
    self.ignore_alive = list(ignore_alive)
    self.ignore_average_freq = list(ignore_average_freq)


def test_ignore_lists_are_not_named():
  sm = _FakeSubMaster(
    {"modelV2", "carState", "uiDebug", "alertDebug", "lateralManeuverPlan"},
    ignore_valid=["uiDebug", "lateralManeuverPlan"],
    ignore_alive=["alertDebug"],
    ignore_average_freq=["modelV2"],
  )
  assert comm_issue_checked_services(sm) == ["carState"]


def test_on_demand_services_are_never_named():
  # The on-demand services publish without valid=True, so they can never pass
  # validation. Naming them in the commIssue log is what sent the diagnosis at
  # the wrong service on every drive.
  on_demand = {s for s, v in SERVICE_LIST.items() if v.frequency == 0}
  assert on_demand, "expected some on-demand services in SERVICE_LIST"

  sm = _FakeSubMaster(set(SERVICE_LIST) - on_demand)
  checked = comm_issue_checked_services(sm)
  assert checked
  assert not (set(checked) & on_demand)


def test_check_never_widens_the_scope():
  # Strict subset of what all_checks() walks: nothing is named that is not a
  # static-frequency service.
  sm = _FakeSubMaster({"carState", "modelV2"}, ignore_alive=["modelV2"])
  assert set(comm_issue_checked_services(sm)) <= sm.static_freq_services
