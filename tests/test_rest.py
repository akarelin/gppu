"""The REST surface: what the walk exposes, what it withholds, how a call binds and dispatches."""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from gppu import AsyncApp, Env, mixin_Rest
from gppu.gppu import _DC


HERE = Path(__file__).resolve().parent               # the classes below are "born here"


def rest_command(method):
  method.rest_command = True
  return method


class _Lamp(_DC):
  name: str
  level: int
  api_key: str
  commands: list

  @property
  def bright(self) -> bool: return self.level > 50

  def stats(self) -> dict: return {'level': self.level}

  @rest_command
  def dim(self, level: int, fade: float = 0.0) -> str:
    self.data['level'] = level
    return f'{self.name} -> {level}'

  @rest_command
  async def blink(self, times: int = 1) -> int:
    await asyncio.sleep(0)
    return times

  def command(self, cmd: str, **args):
    self.data['level'] = 100 if cmd == 'turn_on' else 0
    return cmd

  def refresh(self) -> str: return 'refreshed'
  def wipe(self, target: str) -> None: pass          # granted names need every parameter defaulted


class _Host(mixin_Rest):
  name = 'host'
  rest_read_methods = ('stats',)
  rest_redact = ('api_key',)
  rest_commands = {'_Lamp': ['refresh', 'wipe']}

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

  def test_the_walk_exposes_fields_values_and_commands_and_withholds_the_rest(self) -> None:
    self.assertEqual({n: r['kind'] for n, r in self.rows.items()},
                     {'name': 'field', 'level': 'field', 'commands': 'field', 'bright': 'value', 'stats': 'value',
                      'dim': 'command', 'blink': 'command', 'refresh': 'command'})
    self.assertNotIn('api_key', self.rows)                 # redacted
    self.assertNotIn('wipe', self.rows)                    # granted, but needs a parameter
    self.assertNotIn('command', self.rows)                 # neither marked nor granted
    self.assertNotIn('_Host', self.host.rest_manifest['classes'])   # no members of its own to expose
    self.assertEqual(self.rows['dim']['args'], {'level': {'type': 'int', 'required': True}, 'fade': {'type': 'float', 'required': False}})

  def test_a_gppu_base_name_is_never_the_applications(self) -> None:
    self.assertFalse(self.host._rest_owned(_Lamp, 'get'))        # UserDict's
    self.assertNotIn('get', self.rows)
    for name in mixin_Rest.REST_RESERVED: self.assertNotIn(name, self.rows)

  def test_payload_reads_values_and_links_objects_by_address(self) -> None:
    body, status = self.host.rest_read('lamp', 'desk')
    self.assertEqual(status, 200)
    self.assertEqual(body['members'], {'name': 'desk', 'level': 70, 'commands': ['turn_on', 'turn_off'], 'bright': True, 'stats': {'level': 70}})
    self.assertEqual(set(body['commands']), {'dim', 'blink', 'refresh', 'turn_on', 'turn_off'})
    self.assertEqual(self.host._rest_plain([self.lamp, 1]), ['lamp/desk', 1])
    self.assertEqual(self.host.rest_read('lamp', 'nope'), ({'success': False, 'error': 'no such object'}, 404))
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'dim')[1], 405)
    self.assertEqual(self.host.rest_read('lamp', 'desk', 'api_key')[1], 404)

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
    self.assertEqual((status, body['result']), (200, 'refreshed'))                          # granted by class name
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
