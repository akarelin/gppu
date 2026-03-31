"""
GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging,
data manipulation, and type safety utilities.
"""

from .vault import resolve_secret, set_secret, clear_cache as clear_secret_cache

from .gppu import (
    # Version info
    VER_GPPU,
    VER_GPPU_BASE,
    VER_GPPU_BUILD,

    detect_os,

    # Async helpers
    sync,

    # Global configuration
    TRACE_RULES,

    # Configuration loading
    dict_from_yml,
    dict_to_yml,
    dict_from_json,
    dict_to_json,
    dict_sanitize,
    template_populate,
    dict_template_populate,

    # Dictionary utilities
    deepget,
    deepget_dict,
    deepget_int,
    deepget_float,
    deepget_list,
    deepdict,
    dict_all_paths,
    dict_element_append,
    dict_sort_keylen,

    # Type safety and coercion
    safe_int,
    safe_float,
    safe_list,
    safe_timedelta,

    # Time utilities
    now_str,
    now_ts,
    pretty_timedelta,
    prepend_datestamp,
    append_timestamp,

    # String utilities
    pfy,
    slugify,

    # Colored printing
    pcp,
    dpcp,
    TColor,

    # Logging
    Debug,
    Info,
    Warn,
    Error,
    Dump,

    # Mixins
    _mixin,
    mixin_Config,
    Logger,
    protocol_Logger,
    mixin_Logger,

    # Env
    Env,

    # Config access (aliases for Env.glob*)
    glob,
    glob_int,
    glob_list,
    glob_dict,

    # Foundation classes
    _Logger,
    _Config,
    _Base,
    App,
)


__version__ = VER_GPPU
__all__ = [
    # Version
    'VER_GPPU', 'VER_GPPU_BASE', 'VER_GPPU_BUILD', '__version__',

    # Async helpers
    'sync',

    # Global configuration
    'TRACE_RULES',

    # Configuration
    'dict_from_yml', 'dict_to_yml', 'dict_from_json', 'dict_to_json', 'dict_sanitize',
    'template_populate', 'dict_template_populate',

    # Dictionary utilities
    'deepget', 'deepget_dict', 'deepget_float', 'deepget_int', 'deepget_list',
    'deepdict', 'dict_all_paths', 'dict_element_append', 'dict_sort_keylen',

    # Type utilities
    'safe_int', 'safe_float', 'safe_list', 'safe_timedelta',

    # Time utilities
    'now_str', 'now_ts', 'pretty_timedelta', 'prepend_datestamp', 'append_timestamp',

    # String utilities
    'pfy', 'slugify',

    # Colored printing
    'pcp', 'dpcp', 'TColor',

    # Logging
    'Debug', 'Info', 'Warn', 'Error', 'Dump',

    # Mixins
    '_mixin', 'mixin_Config',
    'Logger', 'protocol_Logger', 'mixin_Logger',

    # Vault / Secrets
    'resolve_secret', 'set_secret', 'clear_secret_cache',

    # Env
    'Env',

    # Config access
    'glob', 'glob_int', 'glob_list', 'glob_dict',

    # Foundation classes
    '_Logger', '_Config', '_Base', 'App',
]