import asyncio
import json
from pathlib import Path
from typing import Literal

import pytest
from textual.widgets import Log

from gppu import App, AsyncApp, CliApp, Env, Provider, run, schema
from gppu.tui import TUIApp


class Store(Provider):
  scheme = 'store'


class Queue(Provider):
  scheme = 'queue'


CONFIG = {'connections': {'store-a': {'provider': 'store', 'path': '/a'},
                          'store-b': {'provider': 'store', 'path': '/b'},
                          'queue-1': {'provider': 'queue', 'host': 'i2'}}}


class Report(CliApp):
  def main(self, since: str = '7d', limit: int = 10, dry_run: bool = False, mode: Literal['fast', 'full'] = 'fast',
           tags: list[str] | None = None, out: Path = Path('.')) -> dict:
    """Report.

    Args:
      since: How far back.
    """
    return {'since': since, 'limit': limit, 'dry_run': dry_run, 'mode': mode, 'tags': tags, 'out': str(out)}


class Needs(CliApp):
  def main(self, name: str) -> str: return name


class UsesQueue(CliApp):
  def main(self, queue: Queue) -> str: return queue.uid


class UsesStore(CliApp):
  def main(self, store: Store) -> str: return store.connection['path']


class Service(AsyncApp):
  async def main(self, queue: Queue, ticks: int = 3) -> list:
    seen = []
    async def tick(n):
      await asyncio.sleep(0)
      seen.append(n)
    for n in range(ticks): self._spawn(tick(n))
    return seen   # the TaskGroup is still open; invoke returns after the ticks finish


class Screen(TUIApp):
  def compose(self): yield Log()
  async def main(self, queue: Queue, lines: int = 2) -> None:
    for n in range(lines): self.query_one(Log).write_line(f'line {n} {queue}')


def test_defaults_from_signature(env):
  env(CONFIG)
  assert Report().invoke() == {'since': '7d', 'limit': 10, 'dry_run': False, 'mode': 'fast', 'tags': None, 'out': '.'}


def test_command_line_is_typed(env, capsys):
  env(CONFIG)
  Report.cli(['--since', '3d', '--limit', '5', '--dry-run', '--mode', 'full', '--tags', 'a', 'b', '--out', 'x'])
  assert json.loads(capsys.readouterr().out) == {'since': '3d', 'limit': 5, 'dry_run': True, 'mode': 'full', 'tags': ['a', 'b'], 'out': 'x'}


def test_configuration_overrides_default_and_command_line_overrides_configuration(env):
  env(CONFIG | {'since': '30d', 'dry_run': False})
  assert Report().invoke()['since'] == '30d'
  assert Report().invoke(since='1d', dry_run=True)['dry_run'] is True


def test_falsy_configuration_is_a_value(env):
  env(CONFIG | {'limit': 0})
  assert Report().invoke()['limit'] == 0


def test_required_parameter_missing_raises(env):
  env(CONFIG)
  with pytest.raises(LookupError, match='--name'): Needs().invoke()


def test_unknown_parameter_raises(env):
  env(CONFIG)
  with pytest.raises(TypeError, match='nme'): Needs().invoke(nme='x')


def test_literal_rejects_other_values(env):
  env(CONFIG)
  with pytest.raises(ValueError): Report().invoke(mode='slow')


def test_single_connection_of_its_type_is_injected(env):
  env(CONFIG)
  assert UsesQueue().invoke() == 'queue-1'


def test_several_connections_of_its_type_need_a_uid(env):
  env(CONFIG)
  with pytest.raises(LookupError, match='--store'): UsesStore().invoke()
  assert UsesStore().invoke(store='store-b') == '/b'


def test_connection_from_configuration(env):
  env(CONFIG | {'store': 'store-a'})
  assert UsesStore().invoke() == '/a'


def test_command_line_offers_the_configured_uids(env, capsys):
  env(CONFIG)
  with pytest.raises(SystemExit): UsesStore.cli(['--store', 'store-c'])
  assert "choose from 'store-a', 'store-b'" in capsys.readouterr().err


def test_connection_is_one_instance(env):
  from gppu import connection
  env(CONFIG)
  assert connection('store-a') is connection('store-a')


def test_schema(env):
  env(CONFIG)
  s = schema(UsesStore().main)
  assert s['properties']['store'] == {'type': 'string', 'format': 'connection-store'} and s['required'] == ['store']
  assert schema(Report().main)['properties']['since']['description'] == 'How far back.'


def test_run_starts_another_app_from_code(env):
  env(CONFIG)
  assert run(UsesStore, store='store-a') == '/a'
  assert run('test_apps:UsesQueue') == 'queue-1'


def test_async_app_resolves_as_cli_and_waits_for_spawned_work(env):
  env(CONFIG)
  assert run(Service, ticks=4) == [0, 1, 2, 3]


def test_tui_is_an_async_app_with_the_same_resolution(env):
  env(CONFIG)
  app = Screen()
  assert isinstance(app, AsyncApp) and isinstance(app, App)
  async def drive():
    app._params = app.params(lines=3)
    async with app._task_scope():
      async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        return list(app.query_one(Log).lines)
  assert asyncio.run(drive()) == ['line 0 Queue(queue-1)', 'line 1 Queue(queue-1)', 'line 2 Queue(queue-1)']


def test_app_name_is_its_file_and_config_is_strict(env):
  env(CONFIG)
  app = Report()
  assert app.name == 'test_apps'
  with pytest.raises(KeyError): app.my('missing')
  with pytest.raises(KeyError): Env.glob('missing')


class Closing(Provider):
  scheme = 'closing'
  def close(self): self.connection['closed'] = True


class Inner(CliApp):
  def main(self, res: Closing) -> bool: return res.connection.get('closed', False)


class Outer(CliApp):
  def main(self, res: Closing) -> list:
    return [run(Inner), res.connection.get('closed', False)]


def test_nested_run_leaves_the_callers_connection_open(env, capsys):
  env(CONFIG | {'connections': CONFIG['connections'] | {'res-1': {'provider': 'closing'}}})
  assert run(Outer) == [False, False]
  from gppu import connection
  res = connection('res-1')
  Outer.cli([])
  assert res.connection['closed'] is True   # the command line is the outermost call and closes them


class Mounted(TUIApp):
  def compose(self): yield Log()
  def on_mount(self): self.query_one(Log).write_line('mounted')
  async def main(self, queue: Queue) -> None: self.query_one(Log).write_line(f'main {queue.uid}')


def test_subclass_on_mount_and_main_both_run(env):
  env(CONFIG)
  app = Mounted()
  async def drive():
    app._params = app.params()
    async with app._task_scope():
      async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        return sorted(app.query_one(Log).lines)
  assert asyncio.run(drive()) == ['main queue-1', 'mounted']


class Scoped(CliApp):
  def __init__(self):
    super().__init__()
    self._config_from_key('scoped')
  def main(self, since: str) -> list: return [since, self.my_int('limit')]


def test_parameters_read_the_apps_own_table(env):
  env(CONFIG | {'since': 'root', 'scoped': {'since': '2d', 'limit': 3}})
  assert Scoped().invoke() == ['2d', 3]


def test_env_logs_as_the_app(env):
  env(CONFIG)
  Env.Info('logged')
