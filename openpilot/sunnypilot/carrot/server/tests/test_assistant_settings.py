import math
import tempfile
import unittest
from pathlib import Path

from openpilot.sunnypilot.carrot.server.services.assistant_settings import AssistantSettings

SUPPORTED_SETTINGS = ('Gap', 'ShowCustomBrightness', 'Negative')
ACCELERATION_CASES = [('absolute', 240, 240), ('delta', -10, 240), ('percent', -4, 240), ('absolute', 239, 239), ('absolute', 1, 1)]


class TestAssistantSettings(unittest.TestCase):
  def setUp(self):
    self.now, self.parked = 100.0, True
    self.values = {'Gap': 100, 'ShowCustomBrightness': 60, 'Negative': -50}
    self.catalog = {name: {'title': name, 'min': (-100 if name == 'Negative' else 0), 'max': 200, 'unit': 5} for name in self.values}
    self.build()

  def build(self):
    # Each parametrized case in the original suite ran against a fresh fixture; rebuild per case.
    self.parked = True
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.writes, self.history = [], []
    self.path = Path(directory.name) / 'grants.json'
    self.service = self.make_service()
    self.token = self.service.enable('http://carrot:7000')
    self.counter = 0

  def make_service(self):
    def write(name, value):
      self.writes.append((name, value))
      self.values[name] = value

    return AssistantSettings(
      self.path, lambda: self.catalog, self.values.get, write, lambda: self.parked, lambda *args: self.history.append(args), lambda: self.now
    )

  def command(self, operation, **fields):
    self.counter += 1
    return {'id': str(self.counter).zfill(43), 'operation': operation, **fields}

  def execute(self, command, token=None):
    return self.service.execute(token or self.token, 'http://carrot:7000', command)

  def prepare(self, **fields):
    return self.execute(self.command('prepare', **{'name': 'Gap', 'mode': 'percent', 'value': 10, **fields}))

  def test_prepare_confirm_readback_and_duplicate_delivery(self):
    proposed = self.prepare()
    self.assertEqual(proposed['proposed'], 110)
    self.assertEqual(self.writes, [])
    commit = self.command('commit', proposal_id=proposed['proposal_id'])
    result = self.execute(commit)
    self.assertEqual(result['current'], 110)
    self.assertEqual(self.execute(commit), result)
    self.assertEqual(self.writes, [('Gap', 110)])
    with self.assertRaises(ValueError):
      self.execute(self.command('commit', proposal_id=proposed['proposal_id']))

  def test_scope_origin_and_cross_connection_proposal(self):
    proposed = self.prepare()
    with self.assertRaises(PermissionError):
      self.execute(self.command('read', name='Gap'), 'wrong')
    with self.assertRaises(PermissionError):
      self.service.execute(self.token, 'http://other:7000', self.command('read', name='Gap'))
    another = self.service.enable('http://carrot:7000')
    with self.assertRaises(ValueError):
      self.execute(self.command('commit', proposal_id=proposed['proposal_id']), another)
    self.assertEqual(self.writes, [])

  def test_expiry_changed_current_and_definition(self):
    for change in ('time', 'value', 'definition'):
      proposal = self.prepare()
      if change == 'time':
        self.now += 60
      if change == 'value':
        self.values['Gap'] += 5
      if change == 'definition':
        self.catalog['Gap']['unit'] = 10
      with self.assertRaises(ValueError):
        self.execute(self.command('commit', proposal_id=proposal['proposal_id']))
    self.assertEqual(self.writes, [])

  def test_prepared_setting_can_apply_after_starting_drive(self):
    proposal = self.prepare()
    self.parked = False
    self.assertEqual(self.execute(self.command('commit', proposal_id=proposal['proposal_id']))['current'], 110)
    self.assertEqual(self.history, [('Gap', 100, 110)])

  def test_supported_settings_can_prepare_and_commit_onroad(self):
    for name in SUPPORTED_SETTINGS:
      with self.subTest(name=name):
        self.build()
        self.parked = False
        proposal = self.prepare(name=name, mode='delta', value=5)
        self.assertIs(proposal['stationary_required'], False)
        self.assertIs(proposal['confirmation_required'], True)
        self.assertEqual(self.writes, [])
        result = self.execute(self.command('commit', proposal_id=proposal['proposal_id']))
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['current'], proposal['current'] + 5)
        self.assertEqual(self.history, [(name, proposal['current'], result['current'])])

  def test_initial_permission_still_requires_stationary(self):
    self.parked = False
    with self.assertRaises(ValueError):
      self.service.enable('http://carrot:7000')

  def test_no_defaults_unknown_internal_or_invalid_values(self):
    self.catalog['DriverMonitoringEnabled'] = {'min': 0, 'max': 1, 'unit': 1}
    self.values['DriverMonitoringEnabled'] = 1
    for name in ('Missing', 'DriverMonitoringEnabled'):
      with self.assertRaises(ValueError):
        self.execute(self.command('read', name=name))
    self.values['Gap'] = None
    with self.assertRaises(ValueError):
      self.execute(self.command('read', name='Gap'))
    self.values['Gap'] = 100
    for value in (True, math.nan, math.inf, '110', 201, -1):
      with self.assertRaises(ValueError):
        self.prepare(mode='absolute', value=value)
    self.assertEqual(self.writes, [])

  def test_integer_rounding_negative_percent_and_noop(self):
    self.assertEqual(self.prepare(mode='percent', value=12.5)['proposed'], 113)
    self.assertEqual(self.prepare(name='Negative')['proposed'], -45)
    with self.assertRaises(ValueError):
      self.prepare(value=0.1)
    with self.assertRaises(ValueError):
      self.prepare(mode='absolute', value=112.5)

  def test_acceleration_minimum_is_not_step_origin(self):
    for mode, amount, target in ACCELERATION_CASES:
      with self.subTest(mode=mode, amount=amount, target=target):
        self.build()
        self.catalog['CruiseMaxVals0'] = {'title': '0–10 km/h', 'min': 1, 'max': 250, 'unit': 5}
        self.values['CruiseMaxVals0'] = 250
        self.parked = False
        proposal = self.prepare(name='CruiseMaxVals0', mode=mode, value=amount)
        self.assertEqual(proposal['proposed'], target)
        self.assertEqual(self.writes, [])
        result = self.execute(self.command('commit', proposal_id=proposal['proposal_id']))
        self.assertEqual(result['current'], target)
        self.assertEqual(self.writes, [('CruiseMaxVals0', target)])

  def test_correction_and_cancel_invalidate_previous_proposals(self):
    old = self.prepare()
    self.prepare(value=20)
    with self.assertRaises(ValueError):
      self.execute(self.command('commit', proposal_id=old['proposal_id']))
    current = self.prepare()
    self.execute(self.command('cancel'))
    with self.assertRaises(ValueError):
      self.execute(self.command('commit', proposal_id=current['proposal_id']))

  def test_persistent_permission_but_no_persistent_commands(self):
    proposed = self.prepare()
    self.service = self.make_service()
    self.assertEqual(self.execute(self.command('read', name='Gap'))['current'], 100)
    with self.assertRaises(ValueError):
      self.execute(self.command('commit', proposal_id=proposed['proposal_id']))
    self.service.revoke(self.token, 'http://carrot:7000')
    self.service = self.make_service()
    with self.assertRaises(PermissionError):
      self.execute(self.command('read', name='Gap'))

  def test_bad_readback_is_never_success_and_not_replayed(self):
    proposed = self.prepare()
    self.service.write = lambda name, value: self.writes.append((name, value))
    command = self.command('commit', proposal_id=proposed['proposal_id'])
    with self.assertRaises(ValueError):
      self.execute(command)
    self.assertEqual(self.execute(command)['status'], 'failed')
    self.assertEqual(len(self.writes), 1)
