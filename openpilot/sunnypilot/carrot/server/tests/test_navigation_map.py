"""Ported from CarrotPilot test_navigation_map.py (pytest → unittest).

The cp fixture patched the feature's Params with a single fake; here one fake
covers both stores the feature touches: the persistent store (Params()) and
the memory store (Params('/dev/shm/params')), since this fork's typed params
make the feature remove() persistent keys and put() dicts into memory.
"""
import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from openpilot.sunnypilot.carrot.server.features import navigation


class FakeParams:
  """Both Params('/dev/shm/params') and Params() share one stores dict."""

  def __init__(self, d="", stores=None):
    self.path = d
    self.stores = stores if stores is not None else {}

  def get(self, key, block=False, return_default=False):
    return self.stores.setdefault(self.path, {}).get(key)

  def put(self, key, value, block=False):
    self.stores.setdefault(self.path, {})[key] = value

  def remove(self, key):
    self.stores.setdefault(self.path, {}).pop(key, None)


class TestNavigationMap(unittest.TestCase):

  def test_destination_lifecycle_and_validation(self):
    stores = {'': {'NavDestination': {'latitude': 1., 'longitude': 2.}}, '/dev/shm/params': {}}
    persistent, memory = stores[''], stores['/dev/shm/params']
    with mock.patch.object(navigation, 'Params', lambda d='': FakeParams(d, stores)), \
         mock.patch.object(navigation, 'get_param_value', lambda key, default='': persistent.get(key, default)):
      async def run():
        app = web.Application()
        navigation.register(app)
        async with TestClient(TestServer(app)) as client:
          response = await client.post('/api/navigation/destination',
                                       json={'latitude': 37., 'longitude': 127., 'place_name': '<script>name</script>'})
          self.assertEqual(response.status, 200)
          self.assertEqual(memory['NavDestinationTemporary']['place_name'], '<script>name</script>')
          self.assertNotIn('NavDestinationTemporary', persistent)
          self.assertEqual(response.headers['Cache-Control'], 'no-store')
          self.assertNotIn('NavDestination', persistent)  # the persistent destination is cleared
          response = await client.get('/api/navigation/destination')
          self.assertEqual(response.headers['Cache-Control'], 'no-store')
          self.assertEqual((await response.json())['destination']['latitude'], 37.)
          for payload in ([], {}, {'latitude': 91, 'longitude': 127}, {'latitude': None, 'longitude': 0}):
            self.assertEqual((await client.post('/api/navigation/destination', json=payload)).status, 400)
          self.assertEqual((await client.get('/api/navigation/search?q=Seoul')).status, 409)
          self.assertEqual((await client.delete('/api/navigation/destination')).status, 200)
          self.assertNotIn('NavDestination', persistent)
          self.assertFalse(memory)
      asyncio.run(run())

  def test_navigation_page_is_served(self):
    async def run():
      app = web.Application()
      navigation.register(app)
      async with TestClient(TestServer(app)) as client:
        response = await client.get('/navigation')
        self.assertEqual(response.status, 200)
        self.assertIn('navigation_map.js', await response.text())
    asyncio.run(run())

  def test_destination_requires_usable_preview(self):
    for fresh, reason, ready in [(True, 'route', False), (True, 'position', False),
                                 (True, 'ready', True), (False, 'ready', False)]:
      with self.subTest(fresh=fresh, reason=reason):
        stores = {'': {}, '/dev/shm/params': {}}
        with mock.patch.object(navigation, 'Params', lambda d='', _s=stores: FakeParams(d, _s)), \
             mock.patch.object(navigation, 'get_param_value', lambda key, default='', _f=fresh: _f), \
             mock.patch.object(navigation, 'preview_fresh', lambda _f=fresh: _f), \
             mock.patch.object(navigation, 'preview_reason', lambda _r=reason: _r):
          response = asyncio.run(navigation.get_destination(None))
          self.assertIs(json.loads(response.text)['map_ready'], ready)

  def test_missing_preview_explains_service_state(self):
    for onroad, reason in [(False, 'offroad'), (True, 'waiting')]:
      with self.subTest(onroad=onroad):
        with tempfile.TemporaryDirectory() as tmp:
          demand_path = Path(tmp) / 'demand'  # a real path is needed: the handler touches the demand file
          stores = {'': {}, '/dev/shm/params': {}}
          with mock.patch.object(navigation, 'WEB_DEMAND_PATH', demand_path), \
               mock.patch.object(navigation, 'Params', lambda d='', _s=stores: FakeParams(d, _s)), \
               mock.patch.object(navigation, 'preview_fresh', lambda: False), \
               mock.patch.object(navigation, 'get_param_value',
                                 lambda key, default='', _o=onroad: _o if key == 'IsOnroad' else default):
            response = asyncio.run(navigation.preview(None))
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers['X-Nav-Map-Status'], reason)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertTrue(demand_path.exists())

  def test_search_reads_fragmented_response_and_keeps_token_server_side(self):
    with mock.patch.object(navigation, 'Params', lambda d='': FakeParams(d, {'': {}, '/dev/shm/params': {}})), \
         mock.patch.object(navigation, 'get_param_value', lambda key, default='': 'pk.private-test'):
      payload = json.dumps({'features': [{'geometry': {'coordinates': [127., 37.]},
                                          'properties': {'full_address': 'Test destination'}}]}).encode()
      calls = []

      async def chunks(_):
        for i in range(0, len(payload), 7):
          yield payload[i:i + 7]

      @asynccontextmanager
      async def get(url, **kwargs):
        calls.append((url, kwargs))
        yield NS(status=200, content=NS(iter_chunked=chunks))

      async def run():
        app = web.Application()
        app['http'] = NS(get=get)
        navigation.register(app)
        async with TestClient(TestServer(app)) as client:
          response = await client.get('/api/navigation/search?q=Seoul')
          body = await response.text()
          self.assertEqual(response.status, 200)
          self.assertNotIn('pk.private-test', body)
          self.assertEqual(response.headers['Cache-Control'], 'no-store')
          self.assertEqual(json.loads(body)['results'][0]['latitude'], 37.)
          self.assertEqual((await client.get('/api/navigation/search?q=Seoul')).status, 429)
      asyncio.run(run())
      url, kwargs = calls[0]
      self.assertEqual(url, 'https://api.mapbox.com/search/geocode/v6/forward')
      self.assertEqual(kwargs['params']['access_token'], 'pk.private-test')
      self.assertEqual(kwargs['params']['permanent'], 'false')


if __name__ == '__main__':
  unittest.main()
