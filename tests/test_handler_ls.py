from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from examples.handler_ls import listing, main
from gppu import Env
from gppu.handlers import GppuFileSystem


def test_listing_only_uses_ls_and_info():
  class Filesystem:
    def info(self):
      return {'name': 'root', 'arbitrary_metadata': {'kept': True}}
    def ls(self, *, recurse):
      assert recurse
      return [{'name': 'child', 'handler_metadata': ['untouched']}]
  fs = Filesystem()
  assert json.loads(listing(fs)) == [fs.info(), *fs.ls(recurse=True)]


def test_main_lists_the_configured_location_without_parameters(tmp_path, monkeypatch, capsys):
  (tmp_path / 'plain.txt').write_text('plain', encoding='utf-8')
  monkeypatch.setattr(Env, 'from_env', staticmethod(lambda **kwargs: None))
  monkeypatch.setattr(Env, 'glob', staticmethod(lambda key: {'location': str(tmp_path)}[key]))
  main()
  rows = json.loads(capsys.readouterr().out)
  assert rows == [GppuFileSystem(tmp_path).info(), *GppuFileSystem(tmp_path).ls(recurse=True)]
  assert rows[0]['gppu']['name'] == tmp_path.name
  assert rows[1]['gppu']['name'] == 'plain.txt'
  assert rows[1]['gppu']['bytes'] == 5


def test_cli_redirected_output_preserves_unicode_on_windows(tmp_path):
  name = 'Заметка — café.md'
  (tmp_path / name).write_text('---\ntitle: Test\n---\nText', encoding='utf-8')
  examples = Path(__file__).resolve().parents[1] / 'examples'
  script = tmp_path / 'run' / 'handler_ls.py'
  script.parent.mkdir()
  script.write_text((examples / 'handler_ls.py').read_text(encoding='utf-8'), encoding='utf-8')
  (script.parent / 'handlers.yaml').write_text(f'location: {tmp_path.as_posix()}\n', encoding='utf-8')
  result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True,
    env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
  assert result.returncode == 0, result.stderr
  rows = json.loads(result.stdout.decode('utf-8'))
  assert name in [row['gppu']['name'] for row in rows]
