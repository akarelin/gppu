# Development Guide

## Config-First Workflow

1.  **Define the Configuration**: Collaborate on the `.yaml` file. **User must approve the final structure.** This is the single source of truth.
2.  **Configuration is Everything**: Paths, credentials, API keys, settings, flags — all in `.yaml`.
3.  **Begin Development**: Only after the config is finalized.
4.  **Zero-Parameter Execution**: All scripts **must** run without parameters. Everything comes from `Env`.

## Interaction Rules

-   **Consult on Missing Features:** If a required feature is not in `gppu`, **stop and ask** the user. Do not implement workarounds.
-   **Consult on Configuration Changes:** If a new config key is needed, **stop and ask**. Do not modify config files without permission.

## Strict Anti-Patterns

-   **NEVER use fallback defaults.** Missing value = config error. Fix the `.yaml`.
-   **NEVER hardcode placeholders** like `user@hostname` or `/path/to/`.
-   **NEVER parse config directly.** Use `Env`, not `dict_from_yml('config.yaml')`.
-   **NEVER use CLI arguments for config.** All settings go in `.yaml`.
-   **NEVER build paths manually.** `Env` handles OS-specific path resolution.
