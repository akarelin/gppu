"""
GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging,
data manipulation, and type safety utilities.
"""

from .fs import Container, DataObject, FileSystem, Location, Provider

from .gppu import (
    # .. Env, its configuration mixins and the regular apps
    Env,
    glob,
    glob_int,
    glob_list,
    glob_dict,
    mixin_Config,
    _Base,
    App,

)

from .app import (
    # .. apps with steps
    AsyncApp,
    _callback_wrapper,
    APIApp,
    mixin_Rest,
    mixin_Mqtt,
    AppService,

    # .. sync lifecycle (AppDaemon / Y2)
    _YMRO,
    YInit,
    YLoad,
    YStart,
)

from .gppu import (
    Span,
    TimeSpan,
    uuid_create,
    y2list,
    y2path,
    Path,
    y2uri,
    y2topic,
    VER_GPPU,

    # .. Human-readable formatters
    format_size,
    format_duration,
    format_since,

    # .. OS detection
    OSType,
    detect_os,

    # .. Logger setup

    # .. Async helpers
    sync,

    # .. Global configuration

    # .. Configuration loading
    dict_from_yml,
    dict_to_yml,
    dict_from_json,
    dict_to_json,
    dict_sanitize,
    template_populate,
    jinja_template,
    jinja,
    jinja_configuration,
    render_template,
    apply_template,

    # .. Dictionary utilities
    deepget,
    deepget_dict,
    deepget_int,
    deepget_float,
    deepget_list,
    deepdict,

    # .. Type safety and coercion
    safe_int,
    safe_float,
    safe_list,
    safe_timedelta,

    # .. Time utilities
    now_str,
    now_ts,
    pretty_timedelta,
    prepend_datestamp,
    append_timestamp,

    # .. String utilities
    pfy,
    slugify,

    # .. Colored printing
    pcp,
    TColor,

    # .. Logging
    Debug,
    Info,
    Warn,
    Error,
    Dump,

    # .. Mixins
    _mixin,
    Logger,
    mixin_Logger,

    # .. Foundation classes
)

from .iot import (
    # .. y2xxx classes
    y2slug,
    y2eid,

    # .. event-loop and device-control bridges
    mixin_EventLoopBridge,
    SerializedControl,
    HTTPControl,
    JSONHTTPControl,
)


__version__ = VER_GPPU
__all__ = [
    'Span', 'TimeSpan', 'uuid_create', 'VER_GPPU', '__version__',
    # .. OS detection
    'OSType', 'detect_os',

    # .. Logger setup

    # .. Async helpers
    'sync',

    # .. Configuration
    'dict_from_yml', 'dict_to_yml', 'dict_from_json', 'dict_to_json', 'dict_sanitize',
    'template_populate', 'jinja_template', 'jinja', 'jinja_configuration', 'render_template', 'apply_template',

    # .. Dictionary utilities
    'deepget', 'deepget_dict', 'deepget_float', 'deepget_int', 'deepget_list',
    'deepdict',

    # .. Type utilities
    'safe_int', 'safe_float', 'safe_list', 'safe_timedelta',

    # .. Time utilities
    'now_str', 'now_ts', 'pretty_timedelta', 'prepend_datestamp', 'append_timestamp',

    # .. String utilities
    'pfy', 'slugify',

    # .. Colored printing
    'pcp', 'TColor',

    # .. Logging
    'Debug', 'Info', 'Warn', 'Error', 'Dump',

    # .. Mixins
    '_mixin', 'mixin_Config',
    'Logger', 'mixin_Logger',

    # .. Vault / Secrets
    'Vault', 'VaultProvider',
    'VaultProviderOSEnviron', 'VaultProviderAzure',

    # .. Human-readable formatters
    'format_size', 'format_duration', 'format_since',

    # .. Env
    'Env',

    # .. Config access
    'glob', 'glob_int', 'glob_list', 'glob_dict',

    # .. Foundation classes
    '_Base', 'App', '_callback_wrapper', 'AsyncApp', 'APIApp', 'mixin_Rest',

    # .. y2xxx classes
    'y2list', 'y2path', 'Path', 'y2uri', 'y2topic', 'y2slug', 'y2eid',

    # .. mqtt library
    'mixin_Mqtt', 'AppService',

    # .. event-loop and device-control bridges
    'mixin_EventLoopBridge', 'SerializedControl', 'HTTPControl', 'JSONHTTPControl',

    # .. lifecycle: sync YMRO (AppDaemon/Y2)
    'YInit', 'YLoad', 'YStart',
]


def __getattr__(name: str):
  """The Vault names import gppu.vault on first use, which gives dict_from_yml ``!secret``."""
  if name in ('Vault', 'VaultProvider', 'VaultProviderOSEnviron', 'VaultProviderAzure'):
    from . import vault
    return getattr(vault, name)
  raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
