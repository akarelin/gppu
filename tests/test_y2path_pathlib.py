"""gppu.gppu.Path: pathlib behaviour alongside y2path's mutable segment interface; y2path itself is no file system path."""
import os
import pathlib
import pickle
from copy import copy, deepcopy

import pytest

from gppu import y2path, y2topic, y2uri
from gppu.gppu import Path


def test_filesystem_operations(tmp_path):
  folder = Path(tmp_path / 'folder')
  folder.mkdir()
  p = folder / 'sample.txt'
  assert p.write_text('proof', encoding='utf-8') == 5
  assert p.read_text(encoding='utf-8') == 'proof'
  assert p.exists() and p.is_file()
  with open(p, encoding='utf-8') as stream:
    assert stream.read() == 'proof'
  assert os.stat(p).st_size == 5
  assert p.parent == pathlib.Path(folder)
  assert p.name == 'sample.txt'
  assert p.suffix == '.txt'
  assert list(folder.glob('*.txt')) == [pathlib.Path(p)]
  assert list(folder.iterdir()) == [pathlib.Path(p)]
  renamed = p.rename(folder / 'renamed.txt')
  assert pathlib.Path(renamed) == pathlib.Path(folder) / 'renamed.txt'
  assert renamed.read_text() == 'proof'
  renamed.unlink()
  assert not renamed.exists()


def test_mutation_updates_filesystem_target(tmp_path):
  (tmp_path / 'first.txt').write_text('first')
  (tmp_path / 'second.csv').write_text('second')
  p = Path(tmp_path / 'first.txt')
  assert p.read_text() == 'first'
  p.data[-1] = 'second.csv'
  assert p.read_text() == 'second'
  assert p.name == 'second.csv'
  assert p.suffix == '.csv'
  p.poptail()
  assert pathlib.Path(p) == tmp_path
  p.iadd('first.txt')
  assert p.read_text() == 'first'


@pytest.mark.parametrize('cls', [y2path, Path])
@pytest.mark.parametrize('clone', [copy, deepcopy, lambda p: p.copy(), lambda p: pickle.loads(pickle.dumps(p))])
def test_copy_preserves_root_and_independent_segments(tmp_path, cls, clone):
  p = cls(tmp_path / 'sample.txt')
  q = clone(p)
  assert type(q) is cls
  assert str(q) == str(p)
  q.data[-1] = 'other.txt'
  assert p.tail == 'sample.txt'
  assert pathlib.Path(str(q)) == tmp_path / 'other.txt'


def test_file_copy(tmp_path):
  p = Path(tmp_path / 'source.txt')
  p.write_text('proof')
  result = p.copy(y2path(tmp_path / 'copied.txt'))
  assert pathlib.Path(result) == tmp_path / 'copied.txt'
  assert result.read_text() == 'proof'
  assert p.copy(target=tmp_path / 'keyword.txt').read_text() == 'proof'


@pytest.mark.parametrize('raw', ['', '/', '/folder/file', '//server/share/file', 'relative/file'])
def test_roots_and_relative_paths(raw):
  assert pathlib.Path(Path(raw)) == pathlib.Path(raw)
  assert pathlib.Path(Path(y2path(raw))) == pathlib.Path(raw)
  assert str(y2path(y2path(raw))) == str(y2path(raw))


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem syntax')
@pytest.mark.parametrize('raw', ['C:/', 'C:/folder/file', 'C:relative', 'C:\\folder\\file', '\\\\server\\share\\file'])
def test_windows_paths(raw):
  assert pathlib.Path(Path(raw)) == pathlib.Path(raw)
  assert pathlib.Path(Path(pathlib.Path(raw))) == pathlib.Path(raw)


def test_class_methods(tmp_path):
  assert Path.cwd() == pathlib.Path.cwd()
  assert Path.home() == pathlib.Path.home()
  assert Path.from_uri(tmp_path.as_uri()) == tmp_path
  assert isinstance(Path.cwd(), Path)


def test_y2path_is_no_filesystem_path():
  p = y2path('a/b')
  assert not isinstance(p, (os.PathLike, pathlib.PurePath))
  for name in ('read_text', 'exists', 'parent', 'name', 'cwd', 'home', 'from_uri'):
    assert not hasattr(p, name)
  with pytest.raises(TypeError):
    pathlib.Path(p)


def test_segment_and_uri_behavior():
  p = y2path('a/b')
  assert list(p) == ['a', 'b']
  assert p.head == 'a' and p.tail == 'b'
  assert str(p / 'c') == 'a/b/c'
  assert str(p) == 'a/b'
  assert p.pophead() == 'a'
  assert str(p) == 'b'
  assert y2topic('mqtt/+/value').is_wildcard()
  assert str(y2uri('custom:///folder?q=value') / 'child') == 'custom:///folder/child?q=value'
  assert not hasattr(p, 'unknown_attribute')
  assert not hasattr(p, '__deepcopy__')
