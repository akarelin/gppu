---
fileClass: Document
created: 2026-09-22
updated: 2026-09-22
generated: { by: Codex/GPT-6, at: 2026-09-22 }
---
# Providers and Locations

A Provider registers its supported URI schemas when its module is loaded. `Providers.schemas` is runtime state; it is never stored in the configuration database. Connections and Locations remain configuration data.

`Providers.load(module)` calls the module's `register(registry)`. A Provider declares its `uid` and a mapping from method names to URI templates. Each method accepts a resolved Connection and the arguments captured from its URI. It returns a filesystem rooted at the selected container.

`resolve(uri)` returns the Provider, method and decoded arguments. `uri(provider, method, **arguments)` constructs the address from those arguments. A trailing `{path}` is a tuple of URI segments and may be empty. Unknown or ambiguous schemas fail directly.

`GppuCatalog` accepts the runtime registry and exposes it through `schemas`. `filesystem(location)` opens that Location's indexing root. Browsing folders beneath it does not create configured Locations. A Provider-Connection pairing can itself be a root Location.

The built-in `file` Provider supports many independently configured Locations. Host-specific access comes from the catalog's declared access mapping. Lake loads its `m365-graph` and `plaud` modules into the same registry. `plaud://` is a complete Location with no further configured subdivisions; recordings are its contents. SharePoint is a component of `m365-graph`.

Provider filesystem reads do not themselves invoke indexing. Constructing a catalog or reading its schemas opens neither the Provider nor its index.
