import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from openpilot.sunnypilot.carrot.server.services.assistant_connection import AssistantConnection, local_origin, proof_id
from openpilot.sunnypilot.carrot.server.services.assistant_settings import AssistantSettings

OLD = 'http://10.225.84.19:7000'
NEW = 'http://192.168.0.178:7000'
BAD_ORIGINS = ['http://evil.test:7000', 'http://8.8.8.8:7000', OLD + '/', OLD + '?x', 'http://user@10.225.84.19:7000', 'https://10.225.84.19:7000']


class TestAssistantConnection(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    root = Path(directory.name)
    stores = {role: (AssistantSettings(root / (role + '.json'), dict, lambda _: 0, lambda *_: None, lambda: True, lambda *_: None), None)
              for role in ('settings', 'drive', 'tools')}
    self.tokens = {role: row[0].enable(OLD) for role, row in stores.items()}
    self.service = AssistantConnection(stores)

  def test_proof_requires_matching_device_and_challenge(self):
    service, tokens = self.service, self.tokens
    ids = {role: proof_id(AssistantSettings._digest(token)) for role, token in tokens.items()}
    reply = service.proof(NEW, OLD, 'n' * 43, ids)['proofs']
    self.assertEqual(set(reply), set(tokens))
    for role, token in tokens.items():
      self.assertEqual(reply[role], hmac.new(AssistantSettings._digest(token).encode(), f'{"n" * 43}\n{OLD}\n{NEW}'.encode(), hashlib.sha256).hexdigest())
    self.assertNotEqual(service.proof(NEW, OLD, 'x' * 43, ids), {'proofs': reply})
    self.assertEqual(service.proof(NEW, 'http://192.168.1.2:7000', 'n' * 43, ids), {'proofs': {}})
    self.assertEqual(service.proof(NEW, OLD, 'n' * 43, {'settings': 'f' * 64}), {'proofs': {}})
    self.assertEqual(proof_id(AssistantSettings._digest('a' * 43)), 'eb64db39233b0ababf39976672ee3877bde4d18a79cbb8ae1dd2c0da96659bfb')

  def test_move_preserves_grants_but_rejects_old_origin_and_clears_pending(self):
    service, tokens = self.service, self.tokens
    called = []
    store = service.stores['drive'][0]
    owner = store._digest(tokens['drive'])
    store.proposals['pending'] = {'owner': owner}
    service.stores['drive'] = (store, called.append)
    self.assertEqual(set(service.move(NEW, OLD, tokens)['moved']), set(tokens))
    self.assertFalse(store.proposals)
    self.assertEqual(called, [owner])
    for role, token in tokens.items():
      current = service.stores[role][0]
      current.authorize(token, NEW)
      with self.assertRaises(PermissionError):
        current.authorize(token, OLD)
    service.move(NEW, OLD, tokens)  # failed response is safe to retry
    self.assertEqual(called, [owner, owner])
    service.move(OLD, NEW, tokens)  # hotspot -> office -> hotspot
    store.authorize(tokens['drive'], OLD)

  def test_no_partial_grant_expansion_or_revoked_credential_restore(self):
    service, tokens = self.service, self.tokens
    with self.assertRaises(PermissionError):
      service.move(NEW, OLD, {**tokens, 'drive': 'z' * 43})
    for role, token in tokens.items():
      service.stores[role][0].authorize(token, OLD)
    service.stores['settings'][0].revoke(tokens['settings'], OLD)
    with self.assertRaises(PermissionError):
      service.move(NEW, OLD, tokens)
    service.move(NEW, OLD, {'tools': tokens['tools']})
    service.stores['drive'][0].authorize(tokens['drive'], OLD)

  def test_reject_nonlocal_origins(self):
    for origin in BAD_ORIGINS:
      with self.subTest(origin=origin):
        self.assertFalse(local_origin(origin))
