import json
from pathlib import Path
import socket
import zipfile

import pytest

from gppu import Container, DataObject, FileLocation, Location
from gppu.handlers import GppuCatalog
from gppu.providers import FileContainer


def test_file_location_uses_its_container_and_keeps_child_boundaries(tmp_path):
  (tmp_path / 'sub').mkdir()
  (tmp_path / 'sub' / 'nested.txt').write_text('nested')
  (tmp_path / 'owned').mkdir()
  (tmp_path / 'owned' / 'separate.txt').write_text('separate')
  (tmp_path / 'readme.md').write_text('---\ntitle: Example\n---\nHello')
  (tmp_path / '.git').mkdir()
  (tmp_path / '.git' / 'config').write_text('not visited')
  catalog = GppuCatalog({'connections': {}, 'locations': {
    'root': {'canonical': tmp_path.as_uri()},
    'child': {'canonical': (tmp_path / 'owned').as_uri(), 'parent': 'root'}}})
  location = catalog.location('root')
  assert [child.uid for child in location.ls()] == ['child']
  walked = list(location.container().walk(level='handlers', recursive=True, boundaries=['owned']))
  assert [folder['name'] for folder, _ in walked] == ['', 'sub']
  rows = {row['name']: row for _, children in walked for row in children}
  assert rows['owned']['boundary'] == 'Location'
  assert rows['.git']['boundary'] == '.git'
  assert rows['readme.md']['markdown']
  assert rows['sub/nested.txt']['size'] == 6
  assert not list(tmp_path.glob('*.sqlite'))


def test_refresh_reports_only_folders_without_marking_files_missing(tmp_path):
  (tmp_path / 'sub').mkdir()
  (tmp_path / 'file.txt').write_text('present')
  rows = list(FileContainer(tmp_path).walk(level='refresh'))
  assert [(r['name'], r['type']) for r in rows[0][1]] == [('sub', 'directory')]


@pytest.mark.parametrize('level', ['files', 'handlers'])
def test_archives_are_not_opened_below_archives_level(tmp_path, monkeypatch, level):
  from gppu.indexing import _IndexHandlers
  archive = tmp_path / 'data.zip'
  with zipfile.ZipFile(archive, 'w') as output:
    output.writestr('inside.txt', 'inside')
  def forbidden(*args, **kwargs):
    pytest.fail('archive contents must not be read at this level')
  monkeypatch.setattr(_IndexHandlers, 'extract_sync', forbidden)
  monkeypatch.setattr(_IndexHandlers, '_archive_children', forbidden)
  walked = list(FileContainer(tmp_path).walk(level=level, recursive=True))
  assert len(walked) == 1
  assert walked[0][1][0]['name'] == 'data.zip'


def test_archive_members_have_original_paths_and_handler_readings(tmp_path):
  with zipfile.ZipFile(tmp_path / 'data.zip', 'w') as output:
    output.writestr('sub/readme.md', '---\ntitle: Archived\n---\nHello')
    output.writestr('sub/plain.txt', 'text')
  walked = list(FileContainer(tmp_path).walk(level='archives', recursive=True))
  rows = {row['name']: row for _, children in walked for row in children}
  assert rows['data.zip/sub/readme.md']['markdown']
  assert rows['data.zip/sub/plain.txt']['size'] == 4
  assert 'container-index-' not in json.dumps(rows, default=str)


def test_a_failed_listing_is_not_a_successful_empty_directory(tmp_path, monkeypatch):
  from gppu.handlers import HandlerError, Record
  from gppu.indexing import _IndexHandlers
  error = HandlerError('file', 'list', tmp_path, 'PermissionError', 'denied')
  monkeypatch.setattr(_IndexHandlers, 'children', lambda *args: ())
  monkeypatch.setattr(_IndexHandlers, 'record', lambda *args: Record(tmp_path, True, 0, None, (), errors=(error,)))
  walk = FileContainer(tmp_path).walk()
  with pytest.raises(OSError, match='directory enumeration failed'):
    next(walk)


def test_missing_and_excluded_roots_fail(tmp_path):
  with pytest.raises(NotADirectoryError):
    list(FileContainer(tmp_path / 'absent').walk())
  (tmp_path / '.git').mkdir()
  with pytest.raises(PermissionError, match='excluded'):
    list(FileContainer(tmp_path / '.git').walk())


def test_provider_container_uses_relative_listing_and_dataobject_reads():
  class Source(Container):
    def ls(self, path='', detail=True):
      return [{'name': 'folder', 'type': 'directory', 'size': 0}] if not path else [
        {'name': 'folder/item', 'type': 'file', 'size': None}]
    def read(self, path):
      return DataObject('provider://source/' + path, {'id': 'item'}, 'native-item')
  walked = list(Source().walk(level='handlers', recursive=True))
  assert walked[1][1][0]['object']['identity'] == 'native-item'


def test_container_and_location_paths_cannot_escape(tmp_path):
  location = FileLocation({'uid': 'test', 'canonical': tmp_path.as_uri()})
  for path in ('../other', '/other', 'sub/../other'):
    with pytest.raises(ValueError):
      list(location.container().walk(path))
  with pytest.raises(ValueError):
    location.container('%2e%2e/other')
  assert location.address('space and #hash.txt').endswith('/space%20and%20%23hash.txt')
  assert Location({'uid': 'plaud', 'canonical': 'plaud://'}).address('recording') == 'plaud://recording'


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows drive roots')
def test_drive_root_is_absolute_and_host_group_is_not_a_container():
  host = socket.gethostname()
  location = FileLocation({'uid': 'drive', 'canonical': f'file://{host}/D:'})
  assert location._root() == Path('D:/')
  with pytest.raises(ValueError, match='select a child Location'):
    FileLocation({'uid': 'host', 'canonical': f'file://{host}'}).container()
  with pytest.raises(ValueError, match='does not identify a file on this host'):
    FileLocation({'uid': 'foreign', 'canonical': 'file://another-host/D:/data'}).container()
