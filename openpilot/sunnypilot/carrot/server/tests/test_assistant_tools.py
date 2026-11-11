import secrets
import tempfile
import unittest
from pathlib import Path

from openpilot.sunnypilot.carrot.server.services.assistant_tools import AssistantTools

FORBIDDEN_ACTIONS = ('shell_cmd', 'git_checkout', 'git_remote_set', 'restore_settings', 'enable_ssh')
JOB_STATUSES = [('git_pull', 'completed'), ('reboot', 'requested'), ('server_tmux_log', 'requested')]


class TestAssistantTools(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.state = {'parked': True, 'now': 0, 'jobs': {}, 'starts': [], 'records': []}
    self.service = self.make()
    self.origin = 'http://192.168.0.1:7000'
    self.token = self.service.enable(self.origin)

  def start(self, body, guard):
    guard()
    self.state['starts'].append(body)
    identity = f'{len(self.state["starts"]):012x}'
    self.state['jobs'][identity] = {'status': 'running', 'result': None, 'guard': guard}
    return identity

  def make(self):
    return AssistantTools(Path(self.directory.name) / 'tools.json', lambda: self.state['parked'], self.start,
                          self.state['jobs'].get, self.state['records'].append, lambda: self.state['now'])

  def execute(self, op, **fields):
    return self.service.execute(self.token, self.origin, {'id': secrets.token_urlsafe(32), 'operation': op, **fields})

  def test_prepare_confirm_fixed_payload_once(self):
    service, state, token, origin = self.service, self.state, self.token, self.origin
    prepared = self.execute('prepare', action='git_reset_hard', target='evil', cmd='rm -rf /')
    self.assertFalse(state['starts'])
    self.assertTrue(prepared['confirmation_required'])
    command = {'id': 'c' * 43, 'operation': 'commit', 'proposal_id': prepared['proposal_id']}
    result = service.execute(token, origin, command)
    self.assertEqual(service.execute(token, origin, command), result)
    self.assertEqual(state['starts'], [{'action': 'git_reset', 'mode': 'hard', 'target': 'HEAD'}])
    with self.assertRaises(ValueError):
      self.execute('commit', proposal_id=prepared['proposal_id'])

  def test_arbitrary_commands_and_sensitive_selection_are_not_executable(self):
    for action in FORBIDDEN_ACTIONS:
      with self.subTest(action=action):
        self.state['starts'].clear()
        with self.assertRaises(ValueError):
          self.execute('prepare', action=action)
        self.assertFalse(self.state['starts'])

  def test_scopes_origin_and_revocation(self):
    service, state, token, origin = self.service, self.state, self.token, self.origin
    prepared = self.execute('prepare', action='reboot')
    for bad_token, bad_origin in [('wrong', origin), (token, 'http://evil')]:
      with self.assertRaises(PermissionError):
        service.execute(bad_token, bad_origin, {'id': 'x' * 43, 'operation': 'commit', 'proposal_id': prepared['proposal_id']})
    other = service.enable(origin)
    with self.assertRaises(ValueError):
      service.execute(other, origin, {'id': 'x' * 43, 'operation': 'commit', 'proposal_id': prepared['proposal_id']})
    service.revoke(token, origin)
    with self.assertRaises(PermissionError):
      self.execute('commit', proposal_id=prepared['proposal_id'])
    self.assertFalse(state['starts'])

  def test_expiry_correction_cancel_and_restart_invalidate_proposals(self):
    service, state, token, origin = self.service, self.state, self.token, self.origin
    first = self.execute('prepare', action='reboot')
    second = self.execute('prepare', action='backup_settings')
    with self.assertRaises(ValueError):
      self.execute('commit', proposal_id=first['proposal_id'])
    state['now'] = 60
    with self.assertRaises(ValueError):
      self.execute('commit', proposal_id=second['proposal_id'])
    third = self.execute('prepare', action='reboot')
    self.execute('cancel')
    with self.assertRaises(ValueError):
      self.execute('commit', proposal_id=third['proposal_id'])
    fourth = self.execute('prepare', action='reboot')
    with self.assertRaises(ValueError):
      self.make().execute(token, origin, {'id': 'c' * 43, 'operation': 'commit', 'proposal_id': fourth['proposal_id']})
    self.assertFalse(state['starts'])

  def test_recheck_movement_and_permission_at_dispatch(self):
    service, state, token, origin = self.service, self.state, self.token, self.origin
    proposal = self.execute('prepare', action='git_pull')
    state['parked'] = False
    with self.assertRaises(ValueError):
      self.execute('commit', proposal_id=proposal['proposal_id'])
    self.assertFalse(state['starts'])
    state['parked'] = True
    job = self.execute('commit', proposal_id=proposal['proposal_id'])
    guard = state['jobs'][job['job_id']]['guard']
    state['parked'] = False
    with self.assertRaises(ValueError):
      guard()
    state['parked'] = True
    service.revoke(token, origin)
    with self.assertRaises(PermissionError):
      guard()

  def test_truthful_private_job_status(self):
    for action, expected in JOB_STATUSES:
      with self.subTest(action=action, expected=expected):
        self.setUp()
        service, state, origin = self.service, self.state, self.origin
        proposal = self.execute('prepare', action=action)
        started = self.execute('commit', proposal_id=proposal['proposal_id'])
        job_id = started['job_id']
        self.assertEqual(self.execute('status', job_id=job_id)['status'], 'running')
        state['jobs'][job_id].update(status='done', result={'ok': True, 'out': 'PRIVATE DIAGNOSTICS'}, log='PRIVATE')
        result = self.execute('status', job_id=job_id)
        self.assertEqual(result, {'status': expected, 'action': action, 'job_id': job_id})
        other = service.enable(origin)
        with self.assertRaises(ValueError):
          service.execute(other, origin, {'id': 'z' * 43, 'operation': 'status', 'job_id': job_id})
        del state['jobs'][job_id]
        self.assertEqual(self.execute('status', job_id=job_id)['status'], 'unknown')

  def test_recording_uses_explicit_target_and_reports_only_request(self):
    state = self.state
    state['parked'] = False
    for action in ['record_start', 'record_start', 'record_stop']:
      p = self.execute('prepare', action=action)
      self.assertEqual(self.execute('commit', proposal_id=p['proposal_id'])['status'], 'requested')
    self.assertEqual(state['records'], [True, True, False])
    self.assertEqual(self.execute('open', action='restore_settings')['status'], 'open_requested')
    self.assertFalse(state['starts'])
