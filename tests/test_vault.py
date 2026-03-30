"""Tests for vault secret resolution."""
import os
from unittest.mock import MagicMock, patch

import pytest

from gppu.vault import resolve_secret, clear_cache, register_yaml_secret_constructor
from gppu import dict_from_yml


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


class TestEnvVarResolution:
    def test_resolve_from_env(self, monkeypatch):
        monkeypatch.setenv("SECRET_MY_PASSWORD", "s3cret")
        assert resolve_secret("my-password") == "s3cret"

    def test_hyphen_to_underscore(self, monkeypatch):
        monkeypatch.setenv("SECRET_NEO4J_DEFAULT_PASSWORD", "neo")
        assert resolve_secret("neo4j-default-password") == "neo"

    def test_uppercase_conversion(self, monkeypatch):
        monkeypatch.setenv("SECRET_LOWER_CASE", "val")
        assert resolve_secret("lower-case") == "val"

    def test_missing_secret_raises(self):
        with pytest.raises(ValueError, match="not found"):
            resolve_secret("nonexistent-secret")


class TestCache:
    def test_cache_returns_same_value(self, monkeypatch):
        monkeypatch.setenv("SECRET_CACHED", "original")
        assert resolve_secret("cached") == "original"
        monkeypatch.delenv("SECRET_CACHED")
        # Should still return cached value
        assert resolve_secret("cached") == "original"

    def test_clear_cache_forces_reresolution(self, monkeypatch):
        monkeypatch.setenv("SECRET_REFRESH", "old")
        assert resolve_secret("refresh") == "old"
        monkeypatch.setenv("SECRET_REFRESH", "new")
        clear_cache()
        assert resolve_secret("refresh") == "new"


class TestYamlIntegration:
    def test_secret_tag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_DB_PASS", "hunter2")
        f = tmp_path / "test.yaml"
        f.write_text("db:\n  password: !secret db-pass\n  host: localhost\n")
        result = dict_from_yml(str(f))
        assert result["db"]["password"] == "hunter2"
        assert result["db"]["host"] == "localhost"


class TestAzureProvider:
    def test_azure_called_when_env_set(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        mock_secret = MagicMock()
        mock_secret.value = "azure-val"
        mock_client = MagicMock()
        mock_client.get_secret.return_value = mock_secret

        with patch("gppu.vault._get_azure", return_value="azure-val"):
            assert resolve_secret("my-key") == "azure-val"

    def test_azure_skipped_when_no_env(self, monkeypatch):
        monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)
        monkeypatch.delenv("GCP_SECRET_PROJECT", raising=False)
        with pytest.raises(ValueError, match="not found"):
            resolve_secret("some-key")


class TestGcpProvider:
    def test_gcp_called_when_env_set(self, monkeypatch):
        monkeypatch.setenv("GCP_SECRET_PROJECT", "my-project")

        with patch("gppu.vault._get_gcp", return_value="gcp-val"):
            assert resolve_secret("my-key") == "gcp-val"

    def test_gcp_skipped_when_no_env(self, monkeypatch):
        monkeypatch.delenv("GCP_SECRET_PROJECT", raising=False)
        monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)
        with pytest.raises(ValueError, match="not found"):
            resolve_secret("some-key")


class TestProviderFallback:
    def test_env_var_takes_priority_over_cloud(self, monkeypatch):
        monkeypatch.setenv("SECRET_PRIO_TEST", "from-env")
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        assert resolve_secret("prio-test") == "from-env"

    def test_azure_before_gcp(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        monkeypatch.setenv("GCP_SECRET_PROJECT", "myproj")

        with patch("gppu.vault._get_azure", return_value="azure-val"), \
             patch("gppu.vault._get_gcp", return_value="gcp-val"):
            assert resolve_secret("my-key") == "azure-val"

    def test_falls_through_to_gcp_when_azure_fails(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        monkeypatch.setenv("GCP_SECRET_PROJECT", "myproj")

        with patch("gppu.vault._get_azure", return_value=None), \
             patch("gppu.vault._get_gcp", return_value="gcp-val"):
            assert resolve_secret("my-key") == "gcp-val"

    def test_error_lists_all_checked_sources(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        monkeypatch.setenv("GCP_SECRET_PROJECT", "myproj")

        with patch("gppu.vault._get_azure", return_value=None), \
             patch("gppu.vault._get_gcp", return_value=None), \
             pytest.raises(ValueError, match="Azure KV.*GCP SM"):
            resolve_secret("missing-key")
