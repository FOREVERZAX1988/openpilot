# ruff: noqa: TID251
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from openpilot.sunnypilot.carrot.server.services.assistant_tools import AssistantTools
from openpilot.sunnypilot.carrot.server.tests.test_assistant_settings_http import load_routes


class TestAssistantToolsHttp(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.starts = []

    def start(body, guard):
      guard()
      self.starts.append(body)
      return 'a' * 12

    routes = load_routes('assistant_tools')
    self.service = AssistantTools(Path(directory.name) / 'grants.json', lambda: True, start, lambda _: None, lambda _: None)
    app = web.Application()
    app[routes.STATE] = self.service
    routes.register(app)
    self.client = TestClient(TestServer(app))
    await self.client.start_server()
    self.addAsyncCleanup(self.client.close)

  async def test_tools_http_enforces_origin_grant_expiry_and_confirmation_flow(self):
    client, starts = self.client, self.starts
    origin = str(client.make_url('/')).rstrip('/')
    headers = {'Origin': origin}
    self.assertEqual((await client.post('/api/assistant/tools/enable', json={'confirmed': True})).status, 403)
    self.assertEqual((await client.post('/api/assistant/tools/enable', json={'confirmed': False}, headers=headers)).status, 400)
    allowed = await (await client.post('/api/assistant/tools/enable', json={'confirmed': True}, headers=headers)).json()
    headers['Authorization'] = f'Bearer {allowed["token"]}'
    command = {'id': 'p' * 43, 'operation': 'prepare', 'action': 'git_pull', 'expires_at': time.time() * 1000 + 20000}
    route = '/api/assistant/tools/execute'
    self.assertEqual((await client.post(route, json={'command': command}, headers={**headers, 'Origin': 'http://evil'})).status, 403)
    self.assertEqual((await client.post(route, data='{}', headers=headers)).status, 415)
    self.assertEqual((await client.post(route, json={'padding': 'x' * 5000}, headers=headers)).status, 413)
    for expiry in [True, 0, time.time() * 1000 + 60000]:
      self.assertEqual((await client.post(route, json={'command': {**command, 'expires_at': expiry}}, headers=headers)).status, 400)
    prepared = await (await client.post(route, json={'command': command}, headers=headers)).json()
    self.assertEqual(prepared['status'], 'prepared')
    self.assertFalse(starts)
    commit = {**command, 'id': 'c' * 43, 'operation': 'commit', 'proposal_id': prepared['proposal_id']}
    result = await (await client.post(route, json={'command': commit}, headers=headers)).json()
    self.assertEqual(result['status'], 'running')
    self.assertEqual(starts, [{'action': 'git_pull'}])
    await client.post(route, json={'command': commit}, headers=headers)
    self.assertEqual(len(starts), 1)
    self.assertEqual((await client.post('/api/assistant/tools/disable', json={}, headers=headers)).status, 200)
    self.assertEqual((await client.post(route, json={'command': commit}, headers=headers)).status, 403)
