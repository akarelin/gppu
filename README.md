# GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging, data manipulation, and type safety utilities.

Originally extracted from the RAN/appdaemon/_adev/Y2 environment loader pattern.

## Features

- **Configuration Management**: YAML loading with includes and templating
- **Logging**: Colored output with trace rules and severity levels  
- **Data Utilities**: Deep dictionary access, type coercion, sanitization
- **Pretty Printing**: Colored console output with formatting
- **Type Safety**: Safe type checking and conversion utilities

## Usage

```python
from gppu import dict_from_yml, deepget, Logger, init_logger

# Load configuration
config = dict_from_yml('config.yaml')

# Access nested values
value = deepget('section/subsection/key', config, default='fallback')

# Initialize logging
init_logger('MyApp', trace_rules={'debug': True})
Logger.Info('Application started')
```

## Version

Current version: 2.18.3.250705