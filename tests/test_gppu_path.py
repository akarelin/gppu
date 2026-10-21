"""gppu.gppu.Path: a file system path that is both a y2path and a pathlib.Path."""
import os
import pathlib
import pickle
from copy import copy, deepcopy

import pytest

from gppu import y2path
from gppu.gppu import Path


def test_both_bases(tmp_path):
  p = Path(tmp_path)
  assert isinstance(p, y2path) and isinstance(p, pathlib.Path)
  assert os.fspath(p) == str(p)
  assert not isinstance(y2path('a/b'), pathlib.Path)


def test_filesystem_operations(tmp_path):
  folder = Path(tmp_path) / 'folder'
  assert isinstance(folder, Path)
  folder.mkdir()
  p = folder / 'sample.txt'
  assert p.write_text('proof', encoding='utf-8') == 5
  assert p.read_text(encoding='utf-8') == 'proof'
  assert p.exists() and p.is_file()
  with open(p, encoding='utf-8') as stream:
    assert stream.read() == 'proof'
  assert p.parent == tmp_path / 'folder' and isinstance(p.parent, Path)
  assert p.name == 'sample.txt' and p.suffix == '.txt' and p.stem == 'sample'
  assert list(folder.glob('*.txt')) == [tmp_path / 'folder' / 'sample.txt']
  assert tmp_path / 'folder' / 'sample.txt' == p
  renamed = p.rename(folder / 'renamed.txt')
  assert renamed.read_text() == 'proof'
  assert renamed.copy(target=folder / 'copied.txt').read_text() == 'proof'
  renamed.unlink()
  assert not renamed.exists()


def test_mutation_updates_filesystem_target(tmp_path):
  (tmp_path / 'first.txt').write_text('first')
  (tmp_path / 'second.csv').write_text('second')
  p = Path(tmp_path / 'first.txt')
  assert p.read_text() == 'first' and p.suffix == '.txt'
  p.data[-1] = 'second.csv'
  assert p.read_text() == 'second'
  assert p.name == 'second.csv' and p.suffix == '.csv'
  p.poptail()
  assert p == tmp_path
  p.iadd('first.txt')
  assert p.read_text() == 'first'


@pytest.mark.parametrize('clone', [copy, deepcopy, lambda p: p.copy(), lambda p: pickle.loads(pickle.dumps(p))])
def test_clone(tmp_path, clone):
  p = Path(tmp_path / 'sample.txt')
  q = clone(p)
  assert isinstance(q, Path) and q == p
  q.data[-1] = 'other.txt'
  assert p.tail == 'sample.txt' and q == tmp_path / 'other.txt'


def test_y2path_behaviour():
  p = Path('/a/b')
  assert str(p) == '/a/b' and p == '/a/b' and hash(p) == hash('/a/b')
  assert list(p) == ['a', 'b'] and len(p) == 2 and p[0] == 'a'
  assert p.head == 'a' and p.tail == 'b' and p.endswith('b') and p.startswith('/a')
  assert str(p / 'c/d') == '/a/b/c/d'
  assert not Path('')
  assert Path.cwd() == pathlib.Path.cwd() and isinstance(Path.home(), Path)
