"""gppu.azure — provider: Azure Key Vault behind ``!secret`` and ``Vault``. Selected by AZURE_KEYVAULT_NAME."""
from __future__ import annotations

from gppu import VaultProvider


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
