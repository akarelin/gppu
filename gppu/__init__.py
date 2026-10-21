"""
GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging,
data manipulation, and type safety utilities.
"""

from .fs import Collection, Container, DataObject, FileSystem, Location, Provider

from .gppu import (
    # Env, its configuration mixins and the regular apps
    Env,
    glob,
    glob_int,
    glob_list,
    glob_dict,
    mixin_Config,
    _Config,
    _Base,
    _App,
    App,
    CliApp,
)

from .app import (
    # apps with steps
    AsyncApp,
    APIApp,
    mixin_Rest,

    # sync lifecycle (AppDaemon / Y2)
    _YMRO,
    YStepper,
    mixin_Stepper,
)

from .gppu import (
    Span,
    TimeSpan,
    y2list,
    y2path,
    y2uri,
    y2topic,

    # Version info
    VER_GPPU,
    VER_GPPU_BASE,
    VER_GPPU_BUILD,

    # Human-readable formatters
    format_size,
    format_duration,
    format_since,

    # OS detection
    OSType,
    detect_os,

    # Logger setup

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
    jinja_template,
    jinja_document,
    JinjaEnvironment,
    JinjaDocument,
    TemplateSet,

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
    mixin_Logger,

    # Foundation classes
    _Logger,
)

from .iot import (
    # y2xxx classes
    y2slug,
    y2eid,

    # mqtt library (aiomqtt optional — gppu[mqtt])
    mixin_Mqtt,
    MqttApp,

    # event-loop and device-control bridges
    mixin_EventLoopBridge,
    SerializedControl,
    HTTPControl,
    JSONHTTPControl,
)

from .app_service import AppService   # an app that runs all the time and reloads its configuration from MQTT

__version__ = VER_GPPU
__all__ = [
    'Span', 'TimeSpan',
    # Version
    'VER_GPPU', 'VER_GPPU_BASE', 'VER_GPPU_BUILD', '__version__',

    # OS detection
    'OSType', 'detect_os',

    # Logger setup

    # Async helpers
    'sync',

    # Global configuration
    'TRACE_RULES',

    # Configuration
    'dict_from_yml', 'dict_to_yml', 'dict_from_json', 'dict_to_json', 'dict_sanitize',
    'template_populate', 'dict_template_populate', 'jinja_template', 'jinja_document',
    'JinjaEnvironment', 'JinjaDocument', 'TemplateSet',

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
    'mixin_Logger',

    # Vault / Secrets
    'Vault', 'VaultProvider',
    'VaultProviderOSEnviron', 'VaultProviderAzure',

    # Human-readable formatters
    'format_size', 'format_duration', 'format_since',

    # Env
    'Env',

    # Config access
    'glob', 'glob_int', 'glob_list', 'glob_dict',

    # Foundation classes
    '_Logger', '_Config', '_Base', '_App', 'App', 'CliApp', 'AsyncApp', 'APIApp', 'mixin_Rest',

    # y2xxx classes
    'y2list', 'y2path', 'y2uri', 'y2topic', 'y2slug', 'y2eid',

    # mqtt library
    'mixin_Mqtt', 'MqttApp', 'AppService',

    # event-loop and device-control bridges
    'mixin_EventLoopBridge', 'SerializedControl', 'HTTPControl', 'JSONHTTPControl',

    # lifecycle: sync YMRO (AppDaemon/Y2)
    'YStepper', 'mixin_Stepper',
]


def __getattr__(name: str):
  """The Vault names import gppu.vault on first use, which gives dict_from_yml ``!secret``."""
  if name in ('Vault', 'VaultProvider', 'VaultProviderOSEnviron', 'VaultProviderAzure'):
    from . import vault
    return getattr(vault, name)
  raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
