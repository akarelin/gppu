"""Tests for full_path (gppu.gppu OS region)."""
import os
from pathlib import Path

import pytest

from gppu.gppu import full_path


class TestFullPath:
    def test_absolute_passthrough(self, tmp_path):
        assert full_path(tmp_path) == tmp_path.resolve()

    def test_relative_against_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert full_path('sub/file.txt') == tmp_path.resolve() / 'sub' / 'file.txt'

    def test_relative_against_base_dir(self, tmp_path):
        assert full_path('file.txt', base_dir=tmp_path) == tmp_path.resolve() / 'file.txt'

    def test_tilde_expansion(self):
        assert full_path('~/x').is_absolute()
        assert '~' not in str(full_path('~/x'))

    def test_env_var_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv('GPPU_TEST_DIR', str(tmp_path))
        assert full_path('$GPPU_TEST_DIR/file.txt') == tmp_path.resolve() / 'file.txt'

    def test_strict_missing_raises(self, tmp_path):
        with pytest.raises(OSError):
            full_path(tmp_path / 'does-not-exist', strict=True)

    def test_strict_existing_ok(self, tmp_path):
        f = tmp_path / 'exists.txt'
        f.write_text('x')
        assert full_path(f, strict=True) == f.resolve()

    def test_returns_path(self):
        assert isinstance(full_path('x'), Path)
