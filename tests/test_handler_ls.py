from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import yaml

from examples.handler_ls import listing, main
from gppu import Env
from gppu.handlers import GppuCatalog


def catalog_for(tmp_path: Path, *locations: Path) -> Path:
  catalog = tmp_path / '.catalog'
  (catalog / socket.gethostname()).mkdir(parents=True)
  rows = [{'id': number, 'path': location.name, 'parent_file_location_id': None, 'root_path': str(location),
    'index': str(location / f'.{location.name}.gppufs.sqlite')} for number, location in enumerate(locations, 1)]
  (catalog / socket.gethostname() / 'locations.yaml').write_text(yaml.safe_dump(rows), encoding='utf-8')
  return catalog


def test_listing_only_uses_ls_and_info():
  class Filesystem:
    def info(self, path):
      return {'name': path or 'root', 'arbitrary_metadata': {'kept': True}}
    def ls(self, path, *, recurse):
      return [{'name': 'child', 'recurse': recurse}]
  fs = Filesystem()
  assert json.loads(listing(fs)) == [fs.info(None), {'name': 'child', 'recurse': False}]
  assert json.loads(listing(fs, 'D:/x')) == [fs.info('D:/x'), {'name': 'child', 'recurse': True}]


def test_main_lists_the_catalog_and_one_location_with_an_argument(tmp_path, monkeypatch, capsys):
  location = tmp_path / 'loc'
  location.mkdir()
  (location / 'plain.txt').write_text('plain', encoding='utf-8')
  catalog = catalog_for(tmp_path, location)
  monkeypatch.setattr(Env, 'from_env', staticmethod(lambda **kwargs: None))
  monkeypatch.setattr(Env, 'glob', staticmethod(lambda key: {'catalog': str(catalog)}[key]))
  monkeypatch.setattr(sys, 'argv', ['handler_ls.py'])
  main()
  rows = json.loads(capsys.readouterr().out)
  assert [row['gppu']['name'] for row in rows] == ['.catalog', 'loc']
  assert rows[1]['gppu']['location']['id'] == 1
  assert not (location / '.loc.gppufs.sqlite').exists()
  monkeypatch.setattr(sys, 'argv', ['handler_ls.py', str(location)])
  main()
  rows = json.loads(capsys.readouterr().out)
  assert [row['gppu']['name'] for row in rows] == ['loc', 'plain.txt']
  assert rows[0]['gppu']['parent'] == GppuCatalog(catalog).root
  assert rows[1]['gppu']['bytes'] == 5


def test_cli_redirected_output_preserves_unicode_on_windows(tmp_path):
  name = 'Заметка — café.md'
  location = tmp_path / 'loc'
  location.mkdir()
  (location / name).write_text('---\ntitle: Test\n---\nText', encoding='utf-8')
  catalog = catalog_for(tmp_path, location)
  examples = Path(__file__).resolve().parents[1] / 'examples'
  script = tmp_path / 'run' / 'handler_ls.py'
  script.parent.mkdir()
  script.write_text((examples / 'handler_ls.py').read_text(encoding='utf-8'), encoding='utf-8')
  (script.parent / 'handlers.yaml').write_text(f'catalog: {catalog.as_posix()}\n', encoding='utf-8')
  result = subprocess.run([sys.executable, str(script), str(location)], cwd=tmp_path, capture_output=True,
    env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
  assert result.returncode == 0, result.stderr
  rows = json.loads(result.stdout.decode('utf-8'))
  assert name in [row['gppu']['name'] for row in rows]
