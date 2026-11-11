# ruff: noqa: TID251 -- HTTP uses cross-host Unix expiry.
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from openpilot.sunnypilot.carrot.bluetooth.model import atomic_json, read_json
from openpilot.sunnypilot.carrot.server.services.assistant_drive import AssistantDrive
from openpilot.sunnypilot.carrot.server.tests.test_assistant_settings_http import load_routes


class TestAssistantDriveHttp(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    self.routes = load_routes('assistant_drive')
    self.parked = [False]
    self.service = AssistantDrive(self.root / 'grants.json', lambda: self.parked[0], self.root / 'runtime')
    app = web.Application()
    app[self.routes.STATE] = self.service
    self.routes.register(app)
    self.client = TestClient(TestServer(app))
    await self.client.start_server()
    self.addAsyncCleanup(self.client.close)

  async def test_http_drive_permission_expiry_delivery_and_revocation(self):
    client, service, parked, root = self.client, self.service, self.parked, self.root
    origin = str(client.make_url('/')).rstrip('/')
    headers = {'Origin': origin}
    base = '/api/assistant/drive/'
    self.assertEqual((await client.post(base + 'enable', json={'confirmed': True})).status, 403)
    self.assertEqual((await client.post(base + 'enable', json={'confirmed': True}, headers=headers)).status, 400)
    parked[0] = True
    self.assertEqual((await client.post(base + 'enable', json={'confirmed': False}, headers=headers)).status, 400)
    response = await client.post(base + 'enable', json={'confirmed': True}, headers=headers)
    self.assertEqual(response.status, 200)
    headers['Authorization'] = 'Bearer ' + (await response.json())['token']
    command = {'id': 'a' * 43, 'operation': 'execute', 'action': 'speed_set', 'value': 100, 'expires_at': time.time() * 1000 + 4000}
    self.assertEqual((await client.post(base + 'execute', json={'command': command}, headers={**headers, 'Origin': 'http://evil.test'})).status, 403)
    self.assertEqual((await client.post(base + 'execute', json={'command': command}, headers={**headers, 'Authorization': 'Bearer wrong'})).status, 403)
    self.assertEqual((await client.post(base + 'execute', json={'command': {**command, 'expires_at': 1}}, headers=headers)).status, 400)
    self.assertEqual((await client.post(base + 'execute', json={'padding': 'x' * 3000}, headers=headers)).status, 413)
    self.assertFalse((service.root / 'speed/request.json').exists())
    parked[0] = False  # Initial grant is parked-only; controller decides subsequent requests.
    response = await client.post(base + 'execute', json={'command': command}, headers=headers)
    self.assertEqual(response.status, 200)
    self.assertEqual((await response.json())['status'], 'waiting')
    sent = read_json(service.root / 'speed/request.json')
    atomic_json(service.root / 'speed/result.json', {'id': command['id'], 'status': 'rejected', 'reason': 'cruise_inactive', 'time': time.monotonic()})
    result = await (await client.post(base + 'execute', json={'command': command}, headers=headers)).json()
    self.assertEqual(result['status'], 'rejected')
    self.assertEqual(read_json(service.root / 'speed/request.json'), sent)
    self.assertEqual((await client.post(base + 'disable', json={}, headers=headers)).status, 200)
    self.assertEqual((await client.post(base + 'execute', json={'command': command}, headers=headers)).status, 403)
