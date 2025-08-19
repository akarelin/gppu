# GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging, data manipulation, and type safety utilities.

## Features

### 🔧 Configuration Management
- **YAML Loading with Includes**: `dict_from_yml()` supports `!include` directives for modular configs
- **Deep Path Access**: `deepget('path/to/nested/key', data)` with fallback support
- **Template Population**: Variable substitution in configuration files
- **Environment Variable Expansion**: Automatic `${VAR}` expansion

### 📊 Logging & Debugging
- **Colored Console Output**: Pretty formatted logs with severity-based colors
- **Trace Rules**: Fine-grained debug control with conditional logging
- **Stack-Aware Tracing**: `dpcp()` shows calling function context
- **File Output**: `Dump()` saves objects to YAML files for inspection

### 🛠️ Data Utilities
- **Type Safety**: `safe_int()`, `coerce_float()`, `safe_isinstance()` with fallbacks
- **Dictionary Tools**: Deep manipulation, sanitization, path enumeration
- **List Processing**: Smart coercion from strings, dicts, and other types
- **Data Sanitization**: Clean complex objects for JSON/YAML serialization

### 🎨 Pretty Printing
- **Colored Terminal Output**: `pcp()` with customizable color schemes
- **Object Formatting**: `pfy()` for readable object dumps
- **Time Utilities**: Human-readable timestamps and deltas

### 📐 Advanced Data Structures
- **Smart Lists**: `y2list`, `y2path` with tokenization and manipulation
- **Entity IDs**: `y2eid` for namespace-aware entity handling
- **Data Classes**: `DC` pseudo-dataclass with property validation

## Usage Examples

### Basic Configuration Loading
```python
from gppu import dict_from_yml, deepget

# Load config with !include support
config = dict_from_yml('app.yaml')

# Access nested configuration
db_host = deepget('database/connection/host', config, default='localhost')
api_key = deepget('services/external/api_key', config)
```

### Advanced Logging Setup
```python
from gppu import init_logger, Logger, dpcp

# Initialize with trace rules
init_logger('MyApp', trace_rules={'debug': True, 'MyClass.method': True})

# Structured logging
Logger.Info('Application', 'WBLUE', 'started successfully')
Logger.Error('Database', 'WRED', 'connection failed')

# Debug with caller context
dpcp('Processing user:', user_id, 'with status:', status)
```

### Configuration with Includes
```yaml
# main.yaml
app:
  name: MyApp
  database: !include database.yaml
  services: !include services.yaml

# database.yaml  
host: localhost
port: 5432
credentials: !include secrets/db-creds.yaml
```

### Type-Safe Data Processing
```python
from gppu import safe_int, deepget_list, coerce_float

# Safe type conversion
port = safe_int(config.get('port'), default=8080)
weights = [coerce_float(x) for x in raw_data]

# Smart list extraction
tags = deepget_list('metadata/tags', config, default=[])
```

## Integration Examples

### As Git Submodule (Recommended)
```bash
# Add to your project
git submodule add https://github.com/akarelin/gppu.git common/gppu
git submodule update --init --recursive
```

```python
# Import in your code
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'common' / 'gppu'))
from gppu import dict_from_yml, deepget, Logger
```

### CRM Dumper Integration
The CRAP/CRM.dumper project uses gppu for robust configuration loading:

```python
# Replaces basic yaml.safe_load() with enhanced loading
class ConfigLoader:
    def _load_config(self):
        # Supports !include directives and complex structures  
        config = dict_from_yml(str(self.config_file))
        return config
        
    def get_config_value(self, path: str, default=None):
        # Deep path access: 'slack/users/AKarelin/token'
        return deepget(path, self.config, default=default)
```

## Branches

- **master** (v2.19.0): Production version. Used by: dev of Y2, RAN, CRAP
- **3.0** (v3.0.0.26): Unfinished, semi-abandoned refactor based on Pydantic and Rich. Used by: Y3
- **LTS**: Original v2.18.3 preserved as backup. Used by master of Y2

## Version History

- **Current (master)**: v2.19.0.250819 - Production version identical to RAN_adev
- **Next (3.0 branch)**: v3.0.0.26 - Major refactor with modern Python patterns
- **Previous**: v2.18.3.250705 - Original extracted version

## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.