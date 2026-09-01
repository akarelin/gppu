#!/usr/bin/env python3
"""Recursively list the current directory through ``gppu.handlers``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from gppu.handlers import (
  FileHandler,
  FileStats,
  Probe,
  Record,
  SessionFile,
  SessionFolder,
  SessionStats,
  file_handler,
)

EMPTY = '-'
INDENT = '  '


def _time(value) -> str:
  return value.astimezone().strftime('%Y-%m-%d %H%M %z') if value else EMPTY


def _span(value) -> str:
  return f'{_time(value[0])} .. {_time(value[1])}' if value else EMPTY


def _items(values) -> str:
  return ','.join(str(value) for value in values) if values else EMPTY


def _value(value) -> str:
  if value is None or value == '':
    return EMPTY
  if isinstance(value, bool):
    return str(value).lower()
  return str(value)


def _stats(value) -> str:
  if isinstance(value, FileStats):
    return (
      f'files={value.files} folders={value.folders} bytes={value.bytes} '
      f'span={_span(value.span)}'
    )
  if isinstance(value, SessionStats):
    return (
      f'files={value.files} sessions={value.sessions} turns={value.turns} '
      f'bytes={value.bytes} span={_span(value.span)} models={_items(value.models)}'
    )
  return repr(value)


def _probe(probe: Probe) -> str:
  obj = probe.obj
  result = f'handler={probe.handler} stats=({_stats(probe.stats)})'
  if isinstance(obj, SessionFile):
    return (
      f'{result} object=SessionFile harness={obj.harness} uid={_value(obj.uid)} '
      f'parent_uid={_value(obj.parent_uid)} subagent={_value(obj.subagent)} '
      f'sidechain_only={_value(obj.sidechain_only)} source_records={len(obj.records)} '
      f'turns={len(obj.turns)} models={_items(obj.models)} topic={_value(obj.topic)} '
      f'name={obj.name}'
    )
  if isinstance(obj, SessionFolder):
    return f'{result} object=SessionFolder harness={obj.harness} logs={len(obj.files)}'
  if isinstance(obj, tuple) and all(isinstance(record, Record) for record in obj):
    return f'{result} object=records records={len(obj)}'
  return f'{result} object={type(obj).__name__} value={obj!r}'


def _archive_records(
  root: Record,
  depth: int,
  handler: FileHandler,
) -> Iterator[tuple[int, Record]]:
  stack = [(depth, record) for record in reversed(handler.children(root))]
  while stack:
    current_depth, record = stack.pop()
    yield current_depth, record
    if record.is_folder:
      stack.extend(
        (current_depth + 1, child)
        for child in reversed(handler.children(record))
      )


def records(
  path: Path,
  handler: FileHandler = file_handler,
) -> Iterator[tuple[int, Record]]:
  """Yield probed filesystem and archive records in recursive display order."""

  found = handler.probe(path)
  root = Path(found[0].path)
  for record in found:
    depth = 0 if record.path == root else len(Path(record.path).relative_to(root).parts)
    yield depth, record
    if 'archive' in record.handlers:
      yield from _archive_records(record, depth + 1, handler)


def _record(depth: int, record: Record) -> list[str]:
  stats = record.stats
  prefix = INDENT * depth
  details = (
    f'type={"folder" if record.is_folder else "file"} size={record.size} '
    f'modified={_time(record.modified_at)} '
    f'files={stats.files if stats else EMPTY} '
    f'folders={stats.folders if stats else EMPTY} '
    f'bytes={stats.bytes if stats else EMPTY} '
    f'span={_span(stats.span) if stats else EMPTY} '
    f'handlers={_items(record.handlers)} location={_value(record.location)} '
    f'path={record.display_path}'
  )
  lines = [f'{prefix}{record.label}', f'{prefix}{INDENT}{details}']
  lines.extend(f'{prefix}{INDENT}{_probe(probe)}' for probe in record.probes)
  return lines


def listing(path: Path, handler: FileHandler = file_handler) -> str:
  """Render a complete recursive listing from handler records."""

  found = list(records(path, handler))
  root = found[0][1]
  stats = root.stats
  lines: list[str] = []
  for depth, record in found:
    lines.extend(_record(depth, record))
  lines.extend([
    '',
    (
      f'{len(found)} records shown; root files={stats.files} folders={stats.folders} '
      f'bytes={stats.bytes} span={_span(stats.span)}'
    ),
  ])
  return '\n'.join(lines)


def main() -> None:
  print(listing(Path.cwd()))


if __name__ == '__main__':
  main()
