from __future__ import annotations

import json

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


def test_main_lists_current_directory_without_parameters(tmp_path, monkeypatch, capsys):
  (tmp_path / 'plain.txt').write_text('plain', encoding='utf-8')
  monkeypatch.chdir(tmp_path)
  main()
  rows = json.loads(capsys.readouterr().out)
  assert Env.glob('location') == '.'
  assert rows == [GppuFileSystem(tmp_path).info(), *GppuFileSystem(tmp_path).ls(recurse=True)]
  assert rows[0]['gppu']['files'] == 1
  assert rows[1]['gppu']['name'] == 'plain.txt'
