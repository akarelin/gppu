"""Tests for gppu.tui.tree — TreeEntry, FilesystemAdapter, GDriveAdapter."""
from __future__ import annotations

import os
import pytest

from gppu.tui.tree import (
    TreeEntry, TreeAdapter,
    FilesystemAdapter, GDriveAdapter,
)


# ── TreeEntry ────────────────────────────────────────────────────────────

class TestTreeEntry:
    def test_defaults(self):
        e = TreeEntry(id='/a', label='a')
        assert e.is_container is False
        assert e.meta == {}

    def test_meta_is_own_dict(self):
        a = TreeEntry(id='a', label='a')
        b = TreeEntry(id='b', label='b')
        a.meta['x'] = 1
        assert 'x' not in b.meta  # no shared default


# ── FilesystemAdapter ────────────────────────────────────────────────────

class TestFilesystemAdapter:
    def test_root_expanded_and_normalized(self, tmp_path):
        os.makedirs(tmp_path / 'sub', exist_ok=True)
        fs = FilesystemAdapter(str(tmp_path))
        root = fs.root()
        assert root.id == str(tmp_path)
        assert root.is_container is True

    def test_lists_children_dirs_first_then_files(self, tmp_path):
        (tmp_path / 'z_file.txt').write_text('x')
        (tmp_path / 'a_file.txt').write_text('y')
        (tmp_path / 'bdir').mkdir()
        (tmp_path / 'adir').mkdir()
        fs = FilesystemAdapter(str(tmp_path))
        kids = list(fs.children(fs.root()))
        # Directory order: adir, bdir; then files: a_file.txt, z_file.txt
        labels = [k.label for k in kids]
        assert labels == ['adir/', 'bdir/', 'a_file.txt', 'z_file.txt']
        # Container flag matches
        assert kids[0].is_container and kids[1].is_container
        assert not kids[2].is_container and not kids[3].is_container

    def test_hides_dotfiles_by_default(self, tmp_path):
        (tmp_path / '.hidden').write_text('')
        (tmp_path / 'visible').write_text('')
        fs = FilesystemAdapter(str(tmp_path))
        labels = [k.label for k in fs.children(fs.root())]
        assert labels == ['visible']

    def test_show_hidden(self, tmp_path):
        (tmp_path / '.hidden').write_text('')
        (tmp_path / 'visible').write_text('')
        fs = FilesystemAdapter(str(tmp_path), show_hidden=True)
        labels = sorted(k.label for k in fs.children(fs.root()))
        assert labels == ['.hidden', 'visible']

    def test_size_metadata(self, tmp_path):
        (tmp_path / 'f.txt').write_text('hello')
        fs = FilesystemAdapter(str(tmp_path))
        kids = list(fs.children(fs.root()))
        (f,) = kids
        assert f.meta['size'] == 5

    def test_non_container_returns_empty(self, tmp_path):
        f = tmp_path / 'x.txt'
        f.write_text('')
        fs = FilesystemAdapter(str(tmp_path))
        entry = TreeEntry(id=str(f), label='x.txt', is_container=False)
        assert list(fs.children(entry)) == []

    def test_max_depth_caps_recursion(self, tmp_path):
        (tmp_path / 'a').mkdir()
        (tmp_path / 'a' / 'b').mkdir()
        (tmp_path / 'a' / 'b' / 'c').mkdir()
        fs = FilesystemAdapter(str(tmp_path), max_depth=1)
        root = fs.root()
        a_kids = list(fs.children(root))
        assert len(a_kids) == 1
        # depth=1 node's children should be empty (cap reached)
        a_entry = a_kids[0]
        b_kids = list(fs.children(a_entry))
        assert b_kids == []

    def test_protocol_compliance(self, tmp_path):
        fs = FilesystemAdapter(str(tmp_path))
        assert isinstance(fs, TreeAdapter)


# ── GDriveAdapter (stubbed service) ──────────────────────────────────────

class _StubDriveService:
    """Mimics ``googleapiclient.discovery.build('drive', 'v3')`` minimally."""

    def __init__(self, folder_map: dict[str, list[dict]]):
        self._folders = folder_map          # parent_id → list of file dicts

    def files(self):
        return self

    def list(self, **params):
        parent = None
        q = params.get('q', '')
        if "'" in q:
            parent = q.split("'")[1]
        return _StubListOp(self._folders.get(parent, []))


class _StubListOp:
    def __init__(self, files):
        self._files = files

    def execute(self):
        return {'files': self._files}


class TestGDriveAdapter:
    def test_root_exposes_label(self):
        a = GDriveAdapter(service=_StubDriveService({}), root_label='All Drive')
        assert a.root().label == 'All Drive'
        assert a.root().is_container is True

    def test_lists_child_folders(self):
        svc = _StubDriveService({
            'root': [
                {'id': 'fld-a', 'name': 'Alpha', 'modifiedTime': '2026-04-01T00:00:00Z'},
                {'id': 'fld-b', 'name': 'Beta',  'modifiedTime': '2026-04-02T00:00:00Z'},
            ],
            'fld-a': [
                {'id': 'fld-c', 'name': 'Gamma', 'modifiedTime': '2026-04-03T00:00:00Z'},
            ],
        })
        a = GDriveAdapter(service=svc)
        kids = list(a.children(a.root()))
        labels = sorted(k.label for k in kids)
        assert labels == ['Alpha', 'Beta']
        # recurse
        alpha = next(k for k in kids if k.label == 'Alpha')
        sub = list(a.children(alpha))
        assert [s.label for s in sub] == ['Gamma']

    def test_non_container_returns_empty(self):
        a = GDriveAdapter(service=_StubDriveService({}))
        leaf = TreeEntry(id='x', label='x', is_container=False)
        assert list(a.children(leaf)) == []

    def test_protocol_compliance(self):
        a = GDriveAdapter(service=_StubDriveService({}))
        assert isinstance(a, TreeAdapter)
