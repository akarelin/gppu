"""A slash path is a string or a y2path, wherever gppu reads configuration by one."""
from gppu import App, AppService, Env
from gppu.gppu import y2path


def test_env_reads_by_y2path():
  Env.from_dict({'a': {'b': 1, 'off': False, 'l': [1], 'd': {'x': 1}}})
  assert Env.glob(y2path('a/b')) == 1 == Env.glob('a/b')
  assert Env.glob(y2path('a/off')) is False
  assert Env.glob_int(y2path('a/b')) == 1
  assert Env.glob_list(y2path('a/l')) == [1]
  assert Env.glob_dict(y2path('a/d')) == {'x': 1}


def test_my_reads_by_y2path():
  Env.from_dict({'a': {'b': 2}})
  app = App()
  assert app.my(y2path('a/b')) == 2 == app.my('a/b')


def test_update_and_observe_by_y2path():
  Env.from_dict({'a': {'b': {'c': 1}}})
  seen = []
  unsubscribe = AppService.on_change(seen.append, y2path('a/b'))
  AppService.update_config({'c': 2}, y2path('a/b'))
  unsubscribe()
  assert Env.glob('a/b/c') == 2 and seen == [frozenset({'a/b/c'})]
