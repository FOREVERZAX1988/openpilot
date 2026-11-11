import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from openpilot.sunnypilot.carrot.server.services.assistant_connection import proof_id
from openpilot.sunnypilot.carrot.server.services.assistant_settings import AssistantSettings
from openpilot.sunnypilot.carrot.server.tests.test_assistant_settings_http import load_routes


class TestAssistantConnectionHttp(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    routes = load_routes('assistant_connection')
    self.store = AssistantSettings(Path(directory.name) / 'grants.json', dict, lambda _: 0, lambda *_: None, lambda: True, lambda *_: None)
    self.old, self.new = 'http://10.225.84.19:7000', 'http://192.168.0.178:7000'
    self.token = self.store.enable(self.old)
    routes.stores = lambda _: {'settings': (self.store, None)}
    app = web.Application()
    routes.register(app)
    self.client = TestClient(TestServer(app))
    await self.client.start_server()
    self.addAsyncCleanup(self.client.close)

  async def test_existing_permission_rebind_http(self):
    store, token = self.store, self.token
    old, new = self.old, self.new
    headers = {'Host': '192.168.0.178:7000', 'Origin': new}
    body = {'previous_origin': old, 'nonce': 'n' * 43, 'identifiers': {'settings': proof_id(store._digest(token))}}
    path = '/api/assistant/connection/'
    self.assertEqual((await self.client.post(path + 'proof', json=body)).status, 403)
    self.assertEqual((await self.client.post(path + 'proof', json=body, headers={**headers, 'Sec-Fetch-Site': 'cross-site'})).status, 403)
    self.assertEqual((await self.client.post(path + 'proof', data='{}', headers=headers)).status, 415)
    self.assertEqual((await self.client.post(path + 'proof', json={'padding': 'x' * 5000}, headers=headers)).status, 413)
    response = await self.client.post(path + 'proof', json=body, headers=headers)
    self.assertEqual(response.status, 200)
    self.assertEqual(set((await response.json())['proofs']), {'settings'})
    self.assertEqual(response.headers['Cache-Control'], 'no-store')
    move = {'previous_origin': old, 'credentials': {'settings': token}}
    self.assertEqual((await self.client.post(path + 'move', json=move, headers=headers)).status, 200)
    store.authorize(token, new)
    with self.assertRaises(PermissionError):
      store.authorize(token, old)
    self.assertEqual((await self.client.post(path + 'move', json={**move, 'credentials': {'drive': token}}, headers=headers)).status, 403)
    self.assertEqual((await self.client.post(path + 'bind', json={}, headers=headers)).status, 400)
