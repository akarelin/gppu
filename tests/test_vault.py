"""Tests for Vault facade + VaultProvider chain."""
from unittest.mock import patch

import pytest
import yaml

from gppu import (
    Vault,
    VaultProvider,
    VaultProviderOSEnviron,
    VaultProviderAzure,
    VaultProviderGcp,
    dict_from_yml,
)


@pytest.fixture(autouse=True)
def _clean():
    Vault.provider_set(None)
    yaml.add_constructor("!secret", lambda l, n: Vault.get(n.value), Loader=yaml.FullLoader)
    yield
    Vault.provider_set(None)


class TestEnvVarResolution:
    """OSEnviron provider resolves SECRET_<NAME> env vars; included in the default chain."""

    def test_resolve_from_env(self, monkeypatch):
        monkeypatch.setenv("SECRET_MY_PASSWORD", "s3cret")
        assert Vault.get("my-password") == "s3cret"

    def test_hyphen_to_underscore(self, monkeypatch):
        monkeypatch.setenv("SECRET_NEO4J_DEFAULT_PASSWORD", "neo")
        assert Vault.get("neo4j-default-password") == "neo"

    def test_uppercase_conversion(self, monkeypatch):
        monkeypatch.setenv("SECRET_LOWER_CASE", "val")
        assert Vault.get("lower-case") == "val"

    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)
        monkeypatch.delenv("GCP_SECRET_PROJECT", raising=False)
        with pytest.raises(ValueError, match="not found"):
            Vault.get("nonexistent-secret")


class TestCache:
    def test_cache_returns_same_value(self, monkeypatch):
        monkeypatch.setenv("SECRET_CACHED", "original")
        assert Vault.get("cached") == "original"
        monkeypatch.delenv("SECRET_CACHED")
        assert Vault.get("cached") == "original"

    def test_clear_cache_forces_reresolution(self, monkeypatch):
        monkeypatch.setenv("SECRET_REFRESH", "old")
        assert Vault.get("refresh") == "old"
        monkeypatch.setenv("SECRET_REFRESH", "new")
        Vault.cache_clear()
        assert Vault.get("refresh") == "new"


class TestYamlIntegration:
    def test_secret_tag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_DB_PASS", "hunter2")
        f = tmp_path / "test.yaml"
        f.write_text("db:\n  password: !secret db-pass\n  host: localhost\n")
        result = dict_from_yml(str(f))
        assert result["db"]["password"] == "hunter2"
        assert result["db"]["host"] == "localhost"


class TestOSEnvironProvider:
    def test_read_only(self):
        p = VaultProviderOSEnviron()
        assert p.writable is False
        with pytest.raises(NotImplementedError, match="read-only"):
            p.set("foo", "bar")


class TestProviderDetection:
    def test_azure_detected_from_env(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        monkeypatch.delenv("GCP_SECRET_PROJECT", raising=False)
        assert isinstance(Vault.provider(), VaultProviderAzure)

    def test_gcp_detected_from_env(self, monkeypatch):
        monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)
        monkeypatch.setenv("GCP_SECRET_PROJECT", "my-project")
        assert isinstance(Vault.provider(), VaultProviderGcp)

    def test_azure_priority_over_gcp(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        monkeypatch.setenv("GCP_SECRET_PROJECT", "myproj")
        assert isinstance(Vault.provider(), VaultProviderAzure)

    def test_no_provider_when_no_env(self, monkeypatch):
        monkeypatch.delenv("AZURE_KEYVAULT_NAME", raising=False)
        monkeypatch.delenv("GCP_SECRET_PROJECT", raising=False)
        assert Vault.provider() is None


class TestProviderExplicitSet:
    def test_explicit_provider_overrides_env(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "envvault")
        explicit = VaultProviderGcp("explicit-project")
        Vault.provider_set(explicit)
        assert Vault.provider() is explicit

    def test_provider_set_none_re_detects(self, monkeypatch):
        monkeypatch.setenv("AZURE_KEYVAULT_NAME", "myvault")
        Vault.provider_set(VaultProviderGcp("ignored"))
        Vault.provider_set(None)
        assert isinstance(Vault.provider(), VaultProviderAzure)


class TestEnvAlwaysWinsOverProvider:
    def test_env_resolves_before_provider(self, monkeypatch):
        monkeypatch.setenv("SECRET_PRIO_TEST", "from-env")
        with patch.object(VaultProviderAzure, "get", return_value="from-azure"):
            Vault.provider_set(VaultProviderAzure("myvault"))
            assert Vault.get("prio-test") == "from-env"

    def test_provider_called_when_env_absent(self):
        with patch.object(VaultProviderAzure, "get", return_value="from-azure"):
            Vault.provider_set(VaultProviderAzure("myvault"))
            assert Vault.get("only-in-azure") == "from-azure"


class TestCreateUpdate:
    def test_create_writes_when_absent(self):
        writes = []
        with patch.object(VaultProviderAzure, "get", return_value=None), \
             patch.object(VaultProviderAzure, "set", side_effect=lambda n, v: writes.append((n, v))):
            Vault.provider_set(VaultProviderAzure("myvault"))
            Vault.create("new-key", "v1")
        assert writes == [("new-key", "v1")]

    def test_create_raises_on_collision(self):
        with patch.object(VaultProviderAzure, "get", return_value="existing"):
            Vault.provider_set(VaultProviderAzure("myvault"))
            with pytest.raises(ValueError, match="already exists"):
                Vault.create("dup", "x")

    def test_update_raises_when_missing_and_no_create_flag(self):
        with patch.object(VaultProviderAzure, "get", return_value=None):
            Vault.provider_set(VaultProviderAzure("myvault"))
            with pytest.raises(ValueError, match="does not exist"):
                Vault.update("absent", "x")

    def test_update_upserts_with_create_flag(self):
        writes = []
        with patch.object(VaultProviderAzure, "get", return_value=None), \
             patch.object(VaultProviderAzure, "set", side_effect=lambda n, v: writes.append((n, v))):
            Vault.provider_set(VaultProviderAzure("myvault"))
            Vault.update("upsert", "v1", create=True)
        assert writes == [("upsert", "v1")]


class TestCreateDesignation:
    """Vault.create(designation=...) appends '-<designation>' to disambiguate names."""

    def test_designation_appended_to_name(self):
        writes = []
        with patch.object(VaultProviderAzure, "get", return_value=None), \
             patch.object(VaultProviderAzure, "set", side_effect=lambda n, v: writes.append((n, v))):
            Vault.provider_set(VaultProviderAzure("myvault"))
            Vault.create("slack-bot-token", "xxx", designation="T01")
        assert writes == [("slack-bot-token-t01", "xxx")]

    def test_no_designation_uses_bare_name(self):
        writes = []
        with patch.object(VaultProviderAzure, "get", return_value=None), \
             patch.object(VaultProviderAzure, "set", side_effect=lambda n, v: writes.append((n, v))):
            Vault.provider_set(VaultProviderAzure("myvault"))
            Vault.create("slack-bot-token", "xxx")
        assert writes == [("slack-bot-token", "xxx")]

    def test_designation_kebab_lowered(self):
        writes = []
        with patch.object(VaultProviderAzure, "get", return_value=None), \
             patch.object(VaultProviderAzure, "set", side_effect=lambda n, v: writes.append((n, v))):
            Vault.provider_set(VaultProviderAzure("myvault"))
            Vault.create("slack-bot-token", "xxx", designation="My_Workspace")
        assert writes == [("slack-bot-token-my-workspace", "xxx")]

    def test_designated_collision_raises(self):
        existing = {"slack-bot-token-t01"}
        with patch.object(VaultProviderAzure, "get", side_effect=lambda n: "x" if n in existing else None):
            Vault.provider_set(VaultProviderAzure("myvault"))
            with pytest.raises(ValueError, match="already exists"):
                Vault.create("slack-bot-token", "xxx", designation="T01")
