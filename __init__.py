"""
GPPU - General Purpose Python Utilities

A comprehensive utility library providing configuration loading, logging,
data manipulation, and type safety utilities.
"""

from .gppu import (
    # Version info
    VER_GPPU,
    VER_GPPU_BASE,
    VER_GPPU_BUILD,
    
    detect_os,

    # Configuration loading
    dict_from_yml,
    dict_to_yml,
    dict_sanitize,
    template_populate,
    dict_template_populate,
    
    # Dictionary utilities  
    deepget,
    deepget_dict,
    deepget_int,
    deepget_list,
    deepdict,
    dict_all_paths,
    dict_element_append,
    dict_sort_keylen,
    
    # Type safety and coercion
    safe_int,
    coerce_int,
    safe_float,
    coerce_float,
    safe_list,
    safe_timedelta,
    safe_isinstance,
    
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
    Logger,
    init_logger,
    Debug,
    Info,
    Warn,
    Error,
    Dump,
    mixin_Logger,
    protocol_Logger,
    
    # Data structures
    y2list,
    y2path,
    y2topic,
    y2slug,
    y2eid,
    
    # Data classes
    DC,
    mixin,
)

__version__ = VER_GPPU
__all__ = [
    # Version
    'VER_GPPU', 'VER_GPPU_BASE', 'VER_GPPU_BUILD', '__version__',
    
    # Configuration
    'dict_from_yml', 'dict_to_yml', 'dict_sanitize', 
    'template_populate', 'dict_template_populate',
    
    # Dictionary utilities
    'deepget', 'deepget_dict', 'deepget_int', 'deepget_list',
    'deepdict', 'dict_all_paths', 'dict_element_append', 'dict_sort_keylen',
    
    # Type utilities
    'safe_int', 'coerce_int', 'safe_float', 'coerce_float', 
    'safe_list', 'safe_timedelta', 'safe_isinstance',
    
    # Time utilities  
    'now_str', 'now_ts', 'pretty_timedelta', 'prepend_datestamp', 'append_timestamp',
    
    # String utilities
    'pfy', 'slugify',
    
    # Colored printing
    'pcp', 'dpcp', 'TColor',
    
    # Logging
    'Logger', 'init_logger', 'Debug', 'Info', 'Warn', 'Error', 'Dump',
    'mixin_Logger', 'protocol_Logger',
    
    # Data structures
    'y2list', 'y2path', 'y2topic', 'y2slug', 'y2eid',
    
    # Data classes
    'DC', 'mixin',
]