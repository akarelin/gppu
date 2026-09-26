"""Path delegation alongside y2path's mutable segment interface."""
import os
import pickle
from copy import copy, deepcopy
from pathlib import Path

import pytest

from gppu import y2path, y2topic, y2uri


def test_filesystem_operations(tmp_path):
  folder = y2path(tmp_path / 'folder')
  folder.mkdir()
  p = folder / 'sample.txt'
  assert p.write_text('proof', encoding='utf-8') == 5
  assert p.read_text(encoding='utf-8') == 'proof'
  assert p.exists() and p.is_file()
  with open(p, encoding='utf-8') as stream:
    assert stream.read() == 'proof'
  assert os.stat(p).st_size == 5
  assert p.parent == Path(folder)
  assert p.name == 'sample.txt'
  assert p.suffix == '.txt'
  assert list(folder.glob('*.txt')) == [Path(p)]
  assert list(folder.iterdir()) == [Path(p)]
  renamed = p.rename(folder / 'renamed.txt')
  assert Path(renamed) == Path(folder) / 'renamed.txt'
  assert renamed.read_text() == 'proof'
  renamed.unlink()
  assert not renamed.exists()


def test_mutation_updates_filesystem_target(tmp_path):
  (tmp_path / 'first.txt').write_text('first')
  (tmp_path / 'second.csv').write_text('second')
  p = y2path(tmp_path / 'first.txt')
  assert p.read_text() == 'first'
  p.data[-1] = 'second.csv'
  assert p.read_text() == 'second'
  assert p.name == 'second.csv'
  assert p.suffix == '.csv'
  p.poptail()
  assert Path(p) == tmp_path
  p.iadd('first.txt')
  assert p.read_text() == 'first'


@pytest.mark.parametrize('clone', [copy, deepcopy, lambda p: p.copy(), lambda p: pickle.loads(pickle.dumps(p))])
def test_copy_preserves_root_and_independent_segments(tmp_path, clone):
  p = y2path(tmp_path / 'sample.txt')
  q = clone(p)
  assert isinstance(q, y2path)
  assert Path(q) == Path(p)
  q.data[-1] = 'other.txt'
  assert p.tail == 'sample.txt'
  assert Path(q) == tmp_path / 'other.txt'


def test_file_copy(tmp_path):
  p = y2path(tmp_path / 'source.txt')
  p.write_text('proof')
  result = p.copy(y2path(tmp_path / 'copied.txt'))
  assert Path(result) == tmp_path / 'copied.txt'
  assert result.read_text() == 'proof'
  assert p.copy(target=tmp_path / 'keyword.txt').read_text() == 'proof'


@pytest.mark.parametrize('raw', ['', '/', '/folder/file', '//server/share/file', 'relative/file'])
def test_roots_and_relative_paths(raw):
  assert Path(y2path(raw)) == Path(raw)
  assert Path(y2path(y2path(raw))) == Path(raw)


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem syntax')
@pytest.mark.parametrize('raw', ['C:/', 'C:/folder/file', 'C:relative', 'C:\\folder\\file', '\\\\server\\share\\file'])
def test_windows_paths(raw):
  assert Path(y2path(raw)) == Path(raw)
  assert Path(y2path(Path(raw))) == Path(raw)


def test_class_methods(tmp_path):
  assert Path(y2path.cwd()) == Path.cwd()
  assert Path(y2path.home()) == Path.home()
  assert Path(y2path.from_uri(tmp_path.as_uri())) == tmp_path


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
