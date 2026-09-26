"""The REST surface: every public member of the application's own classes, nothing declared."""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from gppu import Env, _DC
from gppu import mixin_Rest


HERE = Path(__file__).resolve().parent               # the classes below are "born here"


class _Lamp(_DC):
  name: str
  level: int
  api_key: str

  @property
  def bright(self) -> bool: return self.level > 50

  def stats(self) -> dict: return {'level': self.level}

  def dim(self, level: int, fade: float = 0.0) -> str:
    self.data['level'] = level
    return f'{self.name} -> {level}'

  async def blink(self, times: int = 1) -> int:
    await asyncio.sleep(0)
    return times

  def refresh(self) -> str: return 'refreshed'
  def wipe(self, target: str) -> None: pass
  def get(self, *a): return 'shadowed'                # a UserDict name the application redefines


class _Host(mixin_Rest):
  name = 'host'

  def __init__(self, *lamps): self.lamps = {l.name: l for l in lamps}
  def rest_registries(self): return {'lamp': self.lamps, 'app': {'host': self}}


class RestSurfaceTests(unittest.IsolatedAsyncioTestCase):
  def setUp(self) -> None:
    self._env = Env.data, Env.initialized, getattr(Env, 'app_path', None)
    Env.data, Env.initialized, Env.app_path = {}, True, HERE
    self.lamp = _Lamp(data={'name': 'desk', 'level': 70, 'api_key': 'secret'})
    self.host = _Host(self.lamp)
    self.rows = self.host.rest_manifest['classes']['_Lamp']['members']

  def tearDown(self) -> None:
    Env.data, Env.initialized, Env.app_path = self._env

  def test_every_public_member_is_on_the_surface_and_nothing_else(self) -> None:
    self.assertEqual({n: r['kind'] for n, r in self.rows.items()},
                     {'name': 'value', 'level': 'value', 'api_key': 'value', 'bright': 'value',
                      'stats': 'method', 'dim': 'method', 'blink': 'method', 'refresh': 'method',
                      'wipe': 'method', 'get': 'method'})
    for name in ('pop', 'keys', 'items', 'update', 'copy', *mixin_Rest.REST_RESERVED):
      self.assertNotIn(name, self.rows, name)                        # a base's name, never the application's
    self.assertNotIn('_Host', self.host.rest_manifest['classes'])   # no members of its own
    self.assertEqual(self.rows['dim']['args'], {'level': {'required': True}, 'fade': {'required': False}})
    self.assertEqual(sorted(n for n, r in self.rows.items() if r.get('read')), ['get', 'refresh', 'stats'])   # blink is a coroutine

  def test_a_payload_reads_values_and_names_methods_without_running_them(self) -> None:
    body, status = self.host.rest_read('lamp', 'desk')
    self.assertEqual(status, 200)
    self.assertEqual(body['members'], {'name': 'desk', 'level': 70, 'api_key': 'secret', 'bright': True})
    self.assertEqual(set(body['methods']), {'stats', 'dim', 'blink', 'refresh', 'wipe', 'get'})
    self.assertEqual(self.host.rest_read('lamp', 'nope'), ({'success': False, 'error': 'no such object'}, 404))
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'stats'), ({'stats': {'level': 70}}, 200))   # no argument: GET calls it
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'dim')[1], 405)                             # takes one: POST only
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'nope')[1], 404)

  async def test_a_call_is_the_method_with_the_body_as_its_arguments(self) -> None:
    body, status = await self.host.rest_call('lamp', 'desk', 'dim', {'level': 30})
    self.assertEqual((status, body['result'], self.lamp.level), (200, 'desk -> 30', 30))
    body, status = await self.host.rest_call('lamp', 'desk', 'blink', {'times': 3})
    self.assertEqual((status, body['result']), (200, 3))                                    # a coroutine is awaited
    body, status = await self.host.rest_call('lamp', 'desk', 'refresh', {})
    self.assertEqual((status, body['result']), (200, 'refreshed'))
    self.assertEqual((await self.host.rest_call('lamp', 'desk', 'level', {}))[1], 405)       # a value is not called
    with self.assertRaises(TypeError): await self.host.rest_call('lamp', 'desk', 'dim', {})   # the method's own refusal

  def test_objects_lists_every_roster(self) -> None:
    body, _ = self.host.rest_objects()
    self.assertEqual(body['objects'], {'lamp/desk': '_Lamp', 'app/host': '_Host'})
    self.assertEqual(self.host.rest_objects(kind='_Lamp', full=True)[0]['objects']['lamp/desk']['class'], '_Lamp')


if __name__ == '__main__':
  unittest.main()
