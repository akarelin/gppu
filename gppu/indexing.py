"""Container enumeration and handler readings, independent of index persistence.

The levels and archive extraction behavior come from the September FileIndexer.
Consumers receive relative entries; physical paths and extracted members stay here.
"""
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path, PurePosixPath
import os
import tempfile

from .handlers import (ArchiveHandler, BrowserHandler, FileHandler, FolderHandler,
                       IgnoredHandler, MarkdownHandler, Record, SessionHandler)
from .providers import Location

LEVELS = ('refresh', 'files', 'handlers', 'archives')
CACHE = Path('C:/.cache') if os.name == 'nt' else Path.home() / '.cache'
FOLDER_CLASSES = {'.git': '.git', '.svn': '.git', '__pycache__': 'py_cache',
  '.venv': 'py_cache', 'venv': 'py_cache', 'node_modules': 'npm_cache',
  '.idea': 'ide_config', '.vscode': 'ide_config'}


class _IndexHandlers(FileHandler, IgnoredHandler, MarkdownHandler, BrowserHandler,
                     SessionHandler, ArchiveHandler, FolderHandler):
  """The September indexer's parser set; no per-file Git repository scan."""


def _selection(path, level, boundaries):
  Location.relative(path)
  if level not in LEVELS:
    raise ValueError(f'unknown indexing level: {level}')
  return {str(Location.relative(value)) for value in boundaries}


def walk_container(container, path, level, recursive, boundaries):
  """The same enumeration contract for non-filesystem Containers."""
  boundaries = _selection(path, level, boundaries)

  def visit(folder):
    rows = []
    for item in container.ls(folder):
      row = dict(item)
      name = str(Location.relative(row['name']))
      if name.rpartition('/')[0] != folder or name == folder:
        raise ValueError(f'{name}: listing must contain immediate Container children')
      if row['type'] != 'directory' and level == 'refresh':
        continue
      if name in boundaries:
        row['boundary'] = 'Location'
      elif row['type'] != 'directory' and level in ('handlers', 'archives'):
        obj = container.read(name)
        try:
          row['object'] = {'uri': obj.uri, 'identity': obj.identity, 'kind': obj.kind}
        finally:
          if hasattr(obj.content, 'close'):
            obj.content.close()
      rows.append(row)
    yield {'name': folder, 'type': 'directory', 'size': 0}, rows
    if recursive:
      for row in rows:
        if row['type'] == 'directory' and row['name'] not in boundaries:
          yield from visit(row['name'])
  yield from visit(path)


def walk_files(root: Path, path: str, level: str, recursive: bool,
               boundaries: Iterable[str]) -> Iterator[tuple[dict, list[dict]]]:
  """Read through the handlers, extracting each selected archive once per walk."""
  boundaries = _selection(path, level, boundaries)
  handlers = _IndexHandlers()
  archives = {}
  scratch = None

  def reading(record, name):
    data = record.metadata
    data.pop('path', None)
    data.pop('location', None)
    for probe in record.probes:
      if probe.metadata:
        data[probe.handler] = {key: value for key, value in probe.metadata.items()
                               if key not in ('path', 'location')}
      if probe.handler == 'session':
        sessions = getattr(probe.obj, 'files', None) or [probe.obj]
        data['fingerprints'] = [('session', f'{one.harness}/{one.uid}')
                                for one in sessions if getattr(one, 'uid', None)]
    data.update(name=name, type='directory' if record.is_folder else 'file')
    if record.target is not None:
      data['target'] = str(record.target)
    if record.errors:
      data['unread'] = [f'{error.handler}: {error.error_type}: {error.message}'
                        for error in record.errors]
    return data

  def listed(record):
    for child in handlers.children(record):
      yield child
      if child.is_folder:
        yield from listed(child)

  def extract(record):
    nonlocal scratch
    archive = Path(record.path)
    if archive not in archives:
      wanted = tuple({extension for handler in handlers.handler_types
                      for extension in getattr(handler, 'extensions', ())})
      members = [PurePosixPath(item.path) for item in listed(record)
                 if not item.is_folder and item.name.casefold().endswith(wanted)]
      if not members:
        archives[archive] = {}
      else:
        if scratch is None:
          CACHE.mkdir(parents=True, exist_ok=True)
          scratch = tempfile.TemporaryDirectory(prefix='container-index-', dir=CACHE)
        archives[archive] = handlers.extract_sync(archive,
          Path(scratch.name) / str(len(archives)), members).files

  def probe(record):
    if level not in ('handlers', 'archives') or record.is_folder:
      return record
    if 'archive' in record.handlers and level != 'archives':
      return record
    original = record
    if record.location is not None:
      if level != 'archives':
        return record
      physical = archives[Path(record.location)].get(PurePosixPath(record.path))
      if physical is None:
        return record
    else:
      physical = Path(record.path)
    records = handlers.probe_sync(physical, recursive=False)
    if not records:
      return original
    record = records[0]
    if original.location is not None:
      record = replace(record, path=record.path if 'archive' in record.handlers else original.path,
        location=None if 'archive' in record.handlers else original.location,
        size=original.size, modified_at=original.modified_at)
    return record

  def visit(record, under, in_archive=False):
    if not in_archive and 'archive' not in record.handlers:
      physical = Path(record.path)
      if physical.is_symlink() or physical.is_junction():
        raise PermissionError(f'{under}: a link cannot be selected for traversal')
      if 'ignored' in record.handlers:
        raise PermissionError(f'{under}: selected directory is excluded by {IgnoredHandler.reason(physical)}')
      if not record.is_folder:
        raise NotADirectoryError(str(physical))
    children = handlers.children(record)
    if not in_archive and 'archive' not in record.handlers:
      record = handlers.record(Path(record.path))
      failures = [error for error in record.errors if error.operation in ('list', 'stat')]
      if failures:
        raise OSError(f'{under}: directory enumeration failed: ' + '; '.join(
          f'{error.error_type}: {error.message}' for error in failures))
    rows, descend = [], []
    for child in children:
      name = f'{under}/{child.name}' if under else child.name
      if 'ignored' in child.handlers and not child.is_folder:
        continue
      link = child.target is not None or (child.location is None and isinstance(child.path, Path)
        and (child.path.is_symlink() or child.path.is_junction()))
      if level == 'refresh' and not child.is_folder:
        continue
      child = child if link else probe(child)
      row = reading(child, name)
      if link:
        row['boundary'] = 'link'
        row['target'] = str(child.path.resolve())
      elif name in boundaries:
        row['boundary'] = 'Location'
      elif child.is_folder:
        pattern = IgnoredHandler.match(child.name, FOLDER_CLASSES)
        if pattern or 'ignored' in child.handlers:
          row['boundary'] = FOLDER_CLASSES[pattern] if pattern else 'Ignored'
          if child.location is None:
            row['ignored_reason'] = IgnoredHandler.reason(Path(child.path))
        elif recursive:
          descend.append((child, name, in_archive))
      elif level == 'archives' and 'archive' in child.handlers:
        # An archive read failure remains file evidence and never a successful enumeration.
        try:
          extract(child)
        except Exception as error:
          row['unread'] = [*row.get('unread', []), f'archive: {type(error).__name__}: {error}']
        else:
          if not child.errors:
            descend.append((child, name, True))
      rows.append(row)
    yield reading(record, under), rows
    for child, name, archived in descend:
      yield from visit(child, name, archived)
    handlers.invalidate_sync()

  try:
    selected = handlers.record(root / path)
    yield from visit(selected, path)
  finally:
    handlers.invalidate_sync()
    if scratch is not None:
      scratch.cleanup()
