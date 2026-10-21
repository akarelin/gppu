"""Archived from tests/test_gppufs.py, 2026-10-21: what gppufs read of a Claude export, with the export handlers
(archive/gppu/fs-handlers.py), which gppu/handlers.py does not have."""
import json
import zipfile

from gppu.fs import GppuFileSystem


def test_exported_session_member_paths_remain_relative_after_rename(tmp_path, monkeypatch):
  old = tmp_path / 'old'
  old.mkdir()
  with zipfile.ZipFile(old / 'export.zip', 'w') as archive:
    archive.writestr('conversations.json', json.dumps([{'uuid': 'exported-session', 'chat_messages': []}]))
  fs = GppuFileSystem(tmp_path)
  fs.ls(refresh=True)
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  metadata = fs.info('new/export.zip')
  exported, = metadata['gppu']['claude']['sessions']
  assert exported['location'] == metadata['name']
  assert exported['path'] == 'conversations.json'
