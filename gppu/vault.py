"""gppu.vault — secrets: Vault, its providers, and what ``!secret`` in a configuration file resolves through.

AZURE_KEYVAULT_NAME selects Azure Key Vault (needs the ``vault`` extra); SECRET_<NAME> environment variables are
read first.
"""
from __future__ import annotations

import os


class VaultProvider:
  def get(self, name: str) -> str | None: raise NotImplementedError
  def set(self, name: str, value: str) -> None: raise NotImplementedError(f"{type(self).__name__} is read-only")
  def list(self) -> list[str]: raise NotImplementedError(f"{type(self).__name__} does not support listing")


class VaultProviderOSEnviron(VaultProvider):
  """Reads SECRET_<NAME> (hyphens → underscores, uppercased). Read-only."""
  def get(self, name: str) -> str | None: return os.environ.get('SECRET_' + name.upper().replace('-', '_'))
  def list(self) -> list[str]: return sorted(k[7:].lower().replace('_', '-') for k in os.environ if k.startswith('SECRET_'))


class VaultProviderAzure(VaultProvider):
  def __init__(self, vault_name: str):
    self._vault_name = vault_name
    self._client = None

  def _ensure_client(self):
    if self._client is None:
      from azure.identity import DefaultAzureCredential
      from azure.keyvault.secrets import SecretClient
      self._client = SecretClient(vault_url=f"https://{self._vault_name}.vault.azure.net", credential=DefaultAzureCredential())
    return self._client

  def get(self, name: str) -> str | None:
    from azure.core.exceptions import ResourceNotFoundError
    try: return self._ensure_client().get_secret(name).value
    except ResourceNotFoundError: return None

  def set(self, name: str, value: str) -> None: self._ensure_client().set_secret(name, value)

  def list(self) -> list[str]: return [s.name for s in self._ensure_client().list_properties_of_secrets()]


class Vault:
  """Static facade for secret operations.

  Resolution order on get: OSEnviron (SECRET_<NAME> env var) → persistent provider.
  Writes go to the persistent provider (Vault.provider). OSEnviron is read-only.
  """

  _cache: dict[str, str] = {}
  _provider: VaultProvider | None = None
  _env_provider: VaultProvider = VaultProviderOSEnviron()

  @staticmethod
  def provider_set(provider: VaultProvider | None) -> None:
    """Set the active persistent provider. Pass None to clear and re-detect from env on next use."""
    Vault._provider = provider
    Vault._cache.clear()

  @staticmethod
  def provider() -> VaultProvider:
    """Return the active persistent provider, auto-detecting from env on first call.

    Falls back to VaultProviderOSEnviron when AZURE_KEYVAULT_NAME is not set.
    """
    if Vault._provider is None:
      Vault._provider = Vault._detect()
    return Vault._provider

  @staticmethod
  def _detect() -> VaultProvider:
    """AZURE_KEYVAULT_NAME → VaultProviderAzure; else env-var fallback."""
    vault_name = os.environ.get('AZURE_KEYVAULT_NAME')
    return VaultProviderAzure(vault_name) if vault_name else Vault._env_provider

  @staticmethod
  def get(name: str) -> str:
    if name in Vault._cache: return Vault._cache[name]

    checked: list[str] = [type(Vault._env_provider).__name__]
    val = Vault._env_provider.get(name)

    p = Vault.provider()
    if val is None and p is not Vault._env_provider:
      val = p.get(name)
      checked.append(type(p).__name__)

    if val is None:
      raise ValueError(f"!secret '{name}' not found (checked {', '.join(checked)})")

    Vault._cache[name] = val
    return val

  @staticmethod
  def create(name: str, value: str, designation: str | None = None) -> None:
    """Create a new secret. Raises if name already exists — use update to overwrite.

    designation: optional suffix appended as '-<designation>' (kebab-lower) to disambiguate
    when the base name collides with an existing secret.
    """
    if Vault._exists(name) and designation:
      name = f"{name}-{designation.lower().replace('_', '-')}"
    if Vault._exists(name):
      raise ValueError(f"Secret '{name}' already exists. Use Vault.update to overwrite.")
    Vault._write(name, value)

  @staticmethod
  def update(name: str, value: str, create: bool = False) -> None:
    """Update an existing secret (creates a new version).

    Raises if the name does not exist, unless create=True — in which case it falls through to create.
    """
    if not Vault._exists(name) and not create:
      raise ValueError(f"Secret '{name}' does not exist. Pass create=True to add it, or use Vault.create.")
    Vault._write(name, value)

  @staticmethod
  def _exists(name: str) -> bool:
    return Vault.provider().get(name) is not None

  @staticmethod
  def _write(name: str, value: str) -> None:
    Vault.provider().set(name, value)  # raises NotImplementedError if provider is read-only
    Vault._cache[name] = value

  @staticmethod
  def list() -> list[str]:
    """List secret names available from the active provider.

    Union of env-var fallback names + persistent provider names; sorted, deduped.
    """
    names = set(Vault._env_provider.list())
    p = Vault.provider()
    if p is not Vault._env_provider:
      try: names.update(p.list())
      except NotImplementedError: pass
    return sorted(names)

  @staticmethod
  def cache_clear() -> None:
    Vault._cache.clear()
