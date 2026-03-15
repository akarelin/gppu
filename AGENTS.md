### `gppu` Library: Best Practices for LLM Agents

This document provides a concise guide to the modern and correct usage of the `gppu` library, focusing on configuration, logging, and path management for agent-based development.

---

#### The LLM Development Workflow: Config First

The entire development process begins with the configuration file. This is a strict, non-negotiable rule.

1.  **Define the Configuration**: The User and the LLM collaborate to define the complete structure of the application's configuration in a `.yaml` file. The LLM can propose a first draft, but the **User must review, edit, and approve the final structure.** This file is the single source of truth.

2.  **Configuration is Everything**: The `.yaml` file must contain all information the application needs to run: paths, credentials, API keys, settings, flags, etc.

3.  **Begin Development**: Only after the configuration structure is finalized can the LLM begin writing the application code.

4.  **Zero-Parameter Execution**: All command-line scripts and utilities developed **must** run without any parameters (e.g., `python3 my_app.py`). The application reads everything it needs from the configuration file loaded by `gppu`.

This config-first approach ensures that the application logic is cleanly separated from its environment and settings, making it portable, predictable, and easy to manage.

---

#### LLM Interaction Rules

-   **Consult on Missing Features:** If you determine that a required feature for environment management, logging, or configuration is not available in the `gppu` library, you **must** stop and ask the user for guidance. Do not attempt to implement a workaround.
-   **Consult on Configuration Changes:** If you believe a new key or section needs to be added to a configuration file to complete a task, you **must** stop and ask the user to approve the change. Do not modify configuration files without explicit permission.

---

#### Core Principle: Initialization

All `gppu`-powered applications start by initializing the `Env` object. This is the single entry point for loading the configuration and setting up the environment.

```python
from gppu import Env
from pathlib import Path

# Initialize Env once at the start of your application.
# Env uses class-level state (singleton) — the instance is not stored.
Env(name='app-name', app_path=Path('CRAP/app_root_directory'))
Env.load()
```

-   `name`: A unique identifier for your application (e.g., `file-indexer`).
-   `app_path`: A **relative** path appended to the OS-specific base directory (`D:\Dev` on Windows, `/home/alex` on Linux). For example, `Path('CRAP/file_indexer')` resolves to `D:\Dev\CRAP\file_indexer` on Windows.

---

#### Configuration: The Two-Tier System

Configuration is split into two levels: a central, shared repository for secrets, and application-specific files that import from it.

##### 1. Core Configuration (`RAN/Keys`)

-   The `RAN/Keys` directory is the central, secure repository for all sensitive and shared configuration, such as database credentials, API keys, and other secrets.
-   These files are considered the ultimate source of truth for credentials.

##### 2. Application Configuration

-   Each application has its own `config.yaml` file.
-   This file should be lean and focus only on settings specific to that application.
-   It **must** import all necessary core configurations from `RAN/Keys` using the `!include` directive.

**Example Application `config.yaml`:**

```yaml
# Import shared database credentials from the central repository
db: !include D:\Dev\RAN\Keys\postgres\file_indexer.yaml

# Application-specific settings
imessage_workflow:
  mode: 'full'
  max_age_days: 365
```

---

#### Two Core Usage Patterns

##### Pattern 1: Direct Calls

This pattern is straightforward and suitable for scripts. After initializing `Env`, you use `gppu` functions directly.

```python
from gppu import Env, Info, Error, glob, glob_int
from pathlib import Path

# 1. Initialize Env
Env(name='my-app', app_path=Path('CRAP/my_app'))
Env.load()

# 2. Use gppu functions directly
Info('INFO', 'Application started', 'WGREEN', 'OK', 'DIM', '(config loaded)')

# Access configuration
db_connection = glob('db/connection_string')

if not db_connection:
    Error('WRED', 'FATAL', 'DIM', 'Database connection string is missing!', 'BRIGHT', '(check config.yaml)')
```

##### Pattern 2: Class-Based (using `_Base`)

This pattern is for object-oriented applications. Inheriting from `_Base` automatically provides logging and configuration capabilities.

```python
from gppu import _Base, Env
from pathlib import Path

class DataProcessor(_Base):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._config_from_key('data_processor') # Loads the 'data_processor' section

        # Access config and validate
        self._host = self.my('host')
        if not self._host:
            self.Error('WRED', 'Host is missing for this processor.', data=self._my)

    def process(self):
        self.Info('INFO', 'Processing data for host', 'BRIGHT', self._host)

# --- Application Entry Point ---
Env(name='my-app', app_path=Path('CRAP/my_app'))
Env.load()

processor = DataProcessor()
processor.process()
```

##### Colored Logging

Logging messages **must** be structured for clarity using color codes. Pass strings representing colors and the content to be colored as separate arguments.

**Correct Usage:**
```python
# Good: Structured, colored, and informative
self.Info('INFO', 'Indexing location', 'BRIGHT', location_id, 'DIM', f'({location_path})')
self.Warn('WYELLOW', 'Permission denied', 'DIM', 'accessing', 'BRIGHT', root_path, 'WRED', f'({e})')
self.Error('WRED', 'Error processing file', 'BRIGHT', file_path, 'WRED', f'({e})')
```

---

#### Strict Anti-Patterns (What to Avoid)

Adherence to these rules is critical for maintaining clean, configurable, and maintainable code.

-   **NEVER use fallback defaults.** A missing value is a configuration error that must be fixed in the `.yaml` file.
    -   **❌ WRONG:** `setting = self.my('some/setting', default='default_value')`
    -   **✅ RIGHT:** `setting = self.my('some/setting')` followed by a validation check.

-   **NEVER hardcode example or placeholder values.** Configuration files and code must not contain placeholders like `user@hostname`, `/path/to/downloads`, or `/your/path`.

-   **NEVER parse config files directly.** The `Env` object is the only way to load configuration.
    -   **❌ WRONG:** `my_config = dict_from_yml('config.yaml')`

-   **NEVER use `ConfigLoader`.** This is a deprecated class.

-   **NEVER use command-line arguments for configuration.** All settings belong in `.yaml` files.

-   **NEVER build paths manually.** `gppu` handles OS-specific path resolution automatically. Manual path logic is a critical error.
    -   **❌ WRONG:** `if os_type == OSType.W11: ... else: ...`

---

#### YAML Configuration Rules

-   **No Placeholders:** Your `config.yaml` must be clean of any example or placeholder text.
-   **Use Includes for Modularity:** Import shared configs from `RAN/Keys`.
-   **OS-Specific Paths:** `PathBuilder` handles OS-specific base path resolution automatically via `app_path`. You do not need to define OS-specific roots in your config.
