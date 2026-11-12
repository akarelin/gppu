<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/vault.py e25a647edb6063791bfb9616a3b9c682eb2007b6 -->
`gppu.vault` gives gppu programs named secrets, read from `SECRET_<NAME>` environment variables or from an Azure Key Vault. Importing it also lets YAML files refer to a secret by name with `!secret name`, which `dict_from_yml` resolves through the Vault.

The module has three provider classes and one facade. `VaultProvider` is the base interface with `get`, `set` and `list`. A provider that cannot perform one of these raises `NotImplementedError`. `VaultProviderOSEnviron` reads `SECRET_<NAME>`, with the name uppercased and hyphens changed to underscores. It is read-only. `VaultProviderAzure` reads and writes secrets in the Azure Key Vault named in its constructor, authenticating with `DefaultAzureCredential`. Its `get` returns `None` when the vault does not hold the secret and raises on any other failure.

`Vault` is a static facade that callers use without creating an instance. It keeps one environment provider and one persistent provider. `get` checks the environment first, then the persistent provider, and caches the value it finds. When neither holds the name, it raises a `ValueError` that lists the providers it checked. The persistent provider is the Azure Key Vault when `AZURE_KEYVAULT_NAME` is set, and the environment provider otherwise. `provider_set` replaces the persistent provider and clears the cache. `cache_clear` clears the cache alone. `create` refuses a name that already exists, and `update` refuses a missing name unless `create=True`. Both write only to the persistent provider, and writes update the cache. `list` merges the names from the environment and the persistent provider.

## Using it

Import `Vault` from `gppu.vault` or from `gppu`; the `gppu` import loads the module on first use. A `SECRET_<NAME>` environment variable overrides the vault for that name.

```python
from gppu.vault import Vault

value = Vault.get(name)                  # ValueError when no provider holds the name
Vault.update(name, value, create=True)   # overwrites the secret, or creates it when missing
```
