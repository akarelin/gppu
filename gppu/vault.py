"""
gppu.vault -- Secret resolution via env vars and cloud secret managers.

Three-tier resolution:
  1. Environment variable: SECRET_<NAME> (uppercased, hyphens → underscores)
  2. Cloud provider (auto-detected from env):
     - Azure Key Vault if AZURE_KEYVAULT_NAME is set
     - GCP Secret Manager if GCP_SECRET_PROJECT is set
  3. ValueError with descriptive message

Usage:
    from gppu import resolve_secret
    password = resolve_secret("my-db-password")

Install cloud provider support:
    pip install gppu[vault-azure]   # Azure Key Vault
    pip install gppu[vault-gcp]     # GCP Secret Manager
    pip install gppu[vault]         # Both
"""
from __future__ import annotations

import os


_secret_cache: dict[str, str] = {}
_azure_client: tuple[str, object] | None = None
_gcp_client: tuple[str, object] | None = None


def _get_azure(vault_name: str, name: str) -> str | None:
  global _azure_client
  try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
  except ImportError:
    return None
  try:
    if _azure_client is None or _azure_client[0] != vault_name:
      credential = DefaultAzureCredential()
      client = SecretClient(vault_url=f"https://{vault_name}.vault.azure.net", credential=credential)
      _azure_client = (vault_name, client)
    return _azure_client[1].get_secret(name).value
  except Exception:
    return None


def _get_gcp(project: str, name: str) -> str | None:
  global _gcp_client
  try:
    from google.cloud.secretmanager import SecretManagerServiceClient
  except ImportError:
    return None
  try:
    if _gcp_client is None or _gcp_client[0] != project:
      _gcp_client = (project, SecretManagerServiceClient())
    resource = f"projects/{project}/secrets/{name}/versions/latest"
    response = _gcp_client[1].access_secret_version(request={"name": resource})
    return response.payload.data.decode("utf-8")
  except Exception:
    return None


def resolve_secret(name: str) -> str:
  if name in _secret_cache:
    return _secret_cache[name]

  # 1. Env var override
  env_key = 'SECRET_' + name.upper().replace('-', '_')
  val = os.environ.get(env_key)

  # 2. Cloud providers (auto-detect)
  checked: list[str] = [f'env ${env_key}']

  if val is None:
    vault_name = os.environ.get('AZURE_KEYVAULT_NAME')
    if vault_name:
      val = _get_azure(vault_name, name)
      checked.append(f"Azure KV '{vault_name}'")

  if val is None:
    gcp_project = os.environ.get('GCP_SECRET_PROJECT')
    if gcp_project:
      val = _get_gcp(gcp_project, name)
      checked.append(f"GCP SM '{gcp_project}'")

  if val is None:
    raise ValueError(f"!secret '{name}' not found (checked {', '.join(checked)})")

  _secret_cache[name] = val
  return val


def clear_cache() -> None:
  global _azure_client, _gcp_client
  _secret_cache.clear()
  _azure_client = None
  _gcp_client = None


def register_yaml_secret_constructor():
  import yaml
  def yml_secret(loader, node): return resolve_secret(node.value)
  yaml.add_constructor("!secret", yml_secret, Loader=yaml.FullLoader)
