"""A slash path is a string or a y2path, wherever gppu reads configuration by one."""
from gppu import App
from gppu import glob, glob_dict, glob_int, glob_list
from gppu.gppu import y2path


def test_env_reads_by_y2path(ran):
  ran({'a': {'b': 1, 'off': False, 'l': [1], 'd': {'x': 1}}})
  assert glob(y2path('a/b')) == 1 == glob('a/b')
  assert glob(y2path('a/off')) is False
  assert glob_int(y2path('a/b')) == 1
  assert glob_list(y2path('a/l')) == [1]
  assert glob_dict(y2path('a/d')) == {'x': 1}


def test_my_reads_by_y2path():
  app = App(config={'a': {'b': 2}})
  assert app.my(y2path('a/b')) == 2 == app.my('a/b')
