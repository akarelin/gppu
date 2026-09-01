from __future__ import annotations

import json
import zipfile
from pathlib import Path

from examples.handler_ls import listing, main


def _session(path: Path) -> None:
  values = [
    {
      'type': 'session_meta',
      'timestamp': '2026-09-01T08:00:00Z',
      'payload': {'id': 'codex-demo'},
    },
    {
      'type': 'response_item',
      'timestamp': '2026-09-01T08:01:00Z',
      'payload': {
        'type': 'message',
        'role': 'user',
        'content': [{'type': 'input_text', 'text': 'Show the handlers'}],
      },
    },
  ]
  path.write_text(''.join(json.dumps(value) + '\n' for value in values), encoding='utf-8')


def test_listing_shows_complete_handler_hierarchy(tmp_path: Path) -> None:
  (tmp_path / 'folder').mkdir()
  (tmp_path / 'folder' / 'plain.txt').write_text('plain', encoding='utf-8')
  _session(tmp_path / 'session.jsonl')
  with zipfile.ZipFile(tmp_path / 'bundle.zip', 'w') as archive:
    archive.writestr('inside/nested.txt', 'nested')

  result = listing(tmp_path)

  assert f'path={tmp_path}' in result
  assert 'type=folder size=0' in result
  assert 'files=3 folders=1' in result
  assert 'handlers=session' in result
  assert 'handler=session stats=(files=1 sessions=1 turns=1' in result
  assert 'object=SessionFile harness=codex uid=codex-demo' in result
  assert 'topic=Show the handlers' in result
  assert 'handlers=archive' in result
  assert 'handler=archive stats=(files=1 folders=1 bytes=6' in result
  assert f'location={tmp_path / "bundle.zip"}' in result
  assert f'path={tmp_path / "bundle.zip"}::inside/nested.txt' in result
  assert '7 records shown; root files=3 folders=1' in result


def test_main_lists_current_directory_without_parameters(
  tmp_path: Path,
  monkeypatch,
  capsys,
) -> None:
  (tmp_path / 'plain.txt').write_text('plain', encoding='utf-8')
  monkeypatch.chdir(tmp_path)

  main()

  result = capsys.readouterr().out
  assert f'path={tmp_path}' in result
  assert '2 records shown; root files=1 folders=0' in result
