"""The REST surface: what the walk exposes, what it withholds, how a call binds and dispatches."""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from gppu import AsyncApp, Env, mixin_Rest
from gppu.gppu import _DC


HERE = Path(__file__).resolve().parent               # the classes below are "born here"


class _Lamp(_DC):
  name: str
  level: int
  api_key: str
  commands: list

  @property
  def bright(self) -> bool: return self.level > 50

  def stats(self) -> dict: return {'level': self.level}

  def dim(self, level: int, fade: float = 0.0) -> str:
    self.data['level'] = level
    return f'{self.name} -> {level}'

  async def blink(self, times: int = 1) -> int:
    await asyncio.sleep(0)
    return times

  def command(self, cmd: str, **args):
    self.data['level'] = 100 if cmd == 'turn_on' else 0
    return cmd

  def refresh(self) -> str: return 'refreshed'
  def wipe(self, target: str) -> None: pass


class _Host(mixin_Rest):
  name = 'host'

  def __init__(self, *lamps): self.lamps = {l.name: l for l in lamps}
  def rest_registries(self): return {'lamp': self.lamps, 'app': {'host': self}}


class RestSurfaceTests(unittest.IsolatedAsyncioTestCase):
  def setUp(self) -> None:
    self._env = Env.data, Env.initialized, getattr(Env, 'app_path', None)
    Env.data, Env.initialized, Env.app_path = {}, True, HERE
    self.lamp = _Lamp(data={'name': 'desk', 'level': 70, 'api_key': 'secret', 'commands': ['turn_on', 'turn_off']})
    self.host = _Host(self.lamp)
    self.rows = self.host.rest_manifest['classes']['_Lamp']['members']

  def tearDown(self) -> None:
    Env.data, Env.initialized, Env.app_path = self._env

  def test_every_public_member_of_the_applications_classes_is_on_the_surface(self) -> None:
    """Nothing is declared. A field and a property are values; every public method is
    a command, and one that needs no argument is readable as well."""
    self.assertEqual({n: r['kind'] for n, r in self.rows.items()},
                     {'name': 'field', 'level': 'field', 'commands': 'field', 'api_key': 'field',
                      'bright': 'value', 'stats': 'command', 'dim': 'command', 'blink': 'command',
                      'refresh': 'command', 'wipe': 'command', 'command': 'command'})
    self.assertEqual(sorted(n for n, r in self.rows.items() if r.get('read')), ['blink', 'refresh', 'stats'])
    self.assertNotIn('_Host', self.host.rest_manifest['classes'])   # no members of its own to expose
    self.assertEqual(self.rows['dim']['args'], {'level': {'type': 'int', 'required': True}, 'fade': {'type': 'float', 'required': False}})

  def test_a_gppu_base_name_is_never_the_applications(self) -> None:
    self.assertFalse(self.host._rest_owned(_Lamp, 'get'))        # UserDict's
    self.assertNotIn('get', self.rows)
    for name in mixin_Rest.REST_RESERVED: self.assertNotIn(name, self.rows)

  def test_payload_reads_values_and_links_objects_by_address(self) -> None:
    body, status = self.host.rest_read('lamp', 'desk')
    self.assertEqual(status, 200)
    # A payload reads fields and properties only: calling a method to build one
    # would run it for anyone who listed the objects.
    self.assertEqual(body['members'], {'name': 'desk', 'level': 70, 'api_key': 'secret',
                                       'commands': ['turn_on', 'turn_off'], 'bright': True})
    self.assertEqual(set(body['commands']), {'dim', 'blink', 'refresh', 'wipe', 'stats', 'command',
                                             'turn_on', 'turn_off'})
    self.assertEqual(self.host._rest_plain([self.lamp, 1]), ['lamp/desk', 1])
    self.assertEqual(self.host.rest_read('lamp', 'nope'), ({'success': False, 'error': 'no such object'}, 404))
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'stats'), ({'stats': {'level': 70}}, 200))  # no argument: GET calls it
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'dim')[1], 405)                             # takes one: POST only
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'nope')[1], 404)

  def test_bind_is_exact(self) -> None:
    row = self.rows['dim']
    self.assertEqual(self.host.rest_bind(row, {'level': '40'}), {'level': 40})
    with self.assertRaisesRegex(ValueError, r"missing parameter\(s\) \['level'\]"): self.host.rest_bind(row, {})
    with self.assertRaisesRegex(ValueError, r"unknown parameter\(s\) \['zap'\]"): self.host.rest_bind(row, {'level': 1, 'zap': 2})
    with self.assertRaisesRegex(ValueError, 'expected int, got True'): self.host.rest_bind(row, {'level': True})
    with self.assertRaisesRegex(ValueError, "expected int, got 'loud'"): self.host.rest_bind(row, {'level': 'loud'})

  async def test_call_dispatches_through_the_objects_own_gate(self) -> None:
    body, status = await self.host.rest_call('lamp', 'desk', 'turn_off', {})
    self.assertEqual((status, body['result'], self.lamp.level), (200, 'turn_off', 0))       # declared: command()
    body, status = await self.host.rest_call('lamp', 'desk', 'dim', {'level': 30})
    self.assertEqual((status, body['result'], self.lamp.level), (200, 'desk -> 30', 30))    # marked: bound call
    body, status = await self.host.rest_call('lamp', 'desk', 'blink', {'times': 3})
    self.assertEqual((status, body['result']), (200, 3))                                    # a coroutine is awaited
    body, status = await self.host.rest_call('lamp', 'desk', 'refresh', {})
    self.assertEqual((status, body['result']), (200, 'refreshed'))                          # no marker, no grant
    self.assertEqual((await self.host.rest_call('lamp', 'desk', 'level', {}))[1], 405)
    self.assertEqual((await self.host.rest_call('lamp', 'desk', 'dim', {'level': 'x'}))[1], 400)

  def test_objects_lists_every_roster(self) -> None:
    body, _ = self.host.rest_objects()
    self.assertEqual(body['objects'], {'lamp/desk': '_Lamp', 'app/host': '_Host'})
    self.assertEqual(self.host.rest_objects(kind='_Lamp', full=True)[0]['objects']['lamp/desk']['class'], '_Lamp')

  def test_an_async_app_carries_the_surface(self) -> None:
    self.assertTrue(issubclass(AsyncApp, mixin_Rest))
    self.assertEqual(list(AsyncApp.rest_registries(AsyncApp.__new__(AsyncApp))), ['app'])


if __name__ == '__main__':
  unittest.main()
