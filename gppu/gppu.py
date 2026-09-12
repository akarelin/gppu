from __future__ import annotations

import pprint
import yaml
from yaml.dumper import Dumper
from yaml.representer import SafeRepresenter
from yaml.loader import FullLoader
from yaml.nodes import Node
import re
import os

import inspect
import logging
import sys
import platform
import asyncio
import json
import getpass
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
from jinja2.sandbox import SandboxedEnvironment

from typing import Union, Any, Literal, List, Optional, Tuple, Dict, DefaultDict
from typing import TypeAlias, ClassVar, Callable, Protocol
from collections import defaultdict, UserDict, UserList
from enum import Enum
from functools import wraps, partial, cache
from datetime import datetime, timezone

from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath

from string import Template

from contextlib import contextmanager

from importlib.metadata import PackageNotFoundError, version as _pkg_version
try: _ver_full = _pkg_version('gppu')
except PackageNotFoundError: _ver_full = '0.0.0'
_ver_parts = _ver_full.split('.')
VER_GPPU_BASE = '.'.join(_ver_parts[:3])
VER_GPPU_BUILD = _ver_parts[3] if len(_ver_parts) > 3 else '0'
VER_GPPU = _ver_full


# region OS
class OSType(Enum):
  """Operating System type enumeration"""
  W11 = "W11"
  LINUX = "Linux"
  WSL = "WSL"
  MACOS = "MacOS"
  OTHER = "Other"

def detect_os() -> OSType:
  sysname = platform.system()
  if sysname == "Windows": return OSType.W11
  elif sysname == "Linux":
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release: return OSType.WSL
    return OSType.LINUX
  else: return OSType.OTHER

def full_path(path: str | Path, base_dir: str | Path | None = None, *, strict: bool = False) -> Path:
  """
    Resolve a user-supplied path to a local Path suitable for open()/read/write.

    Expands environment variables and ~. Leaves native absolute paths absolute.
    Resolves relative paths against base_dir, or cwd when base_dir is None.
    On Windows, maps WSL-style drive paths like /mnt/d/x to D:\\x.

    If strict=True, requires the resolved path to exist.
  """
  raw = os.path.expandvars(str(path))

  if detect_os() == OSType.W11 and len(raw) >= 7 and raw.startswith('/mnt/') and raw[5].isalpha() and raw[6] == '/': result = Path(f'{raw[5].upper()}:\\') / raw[7:]
  else: result = Path(raw)
  result = result.expanduser()

  if not result.is_absolute(): result = (Path.cwd() if base_dir is None else full_path(base_dir)) / result
  
  return result.resolve(strict=strict)
# endregion


# region Safe typecasting
def safe_float(o, default: float = float("NaN")) -> float:
  if o is None: return default
  if isinstance(o, str):
    o = o.removesuffix("°c")
    o = o.removesuffix("%")
  try: result = float(o)
  except: result = default
  return result
def safe_int(o, default: int = 0) -> int: return int(_) if (_ := safe_float(o, default)) else default
def safe_list(o) -> list:
  result = []
  if isinstance(o, str): result = [o]
  elif isinstance(o, list): result = [element for element in o if element]
  elif isinstance(o, dict): result = list(o.keys())
  return result
def safe_timedelta(o: object) -> float:
  try: then = datetime.fromisoformat(str(o)).timestamp()
  except: then = 0.0
  return now_ts() - then
# endregion


# region Dict utils: deepget, dict_all_paths
deepdict: Callable[[], DefaultDict[Any, Any]] = lambda: defaultdict(deepdict)


def deepget(path: str, d: dict, default=None):
  if '/' in path and path not in d.keys():
    _ = dict(d)
    for pp in path.split('/'):
      _ = _.get(pp)
      if not _: break
    return _ if _ else default
  return d.get(path, default)
def deepget_int(path: str, d: dict, default: int = 0) -> int:
  """ Returns int at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, int) else default
def deepget_float(path: str, d: dict, default: float = float("NaN")) -> float:
  """ Returns float at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, float) else default
def deepget_list(path: str, d: dict, default: list = []) -> list:
  """ Returns list at path, or default if not found """
  return _ if isinstance(_ := deepget(path, d, default), list) else default
def deepget_dict(path: str, d: dict, default: dict = {}) -> dict:
  """ Returns dict at path, or default if not found """
  return _ if isinstance(_ := deepget(path, d, default), dict) else default


def dict_sort_keylen(d, reverse: bool = True) -> dict:
  if not isinstance(d,dict): return {}
  return dict(sorted(d.items(), key=lambda key: len(key[0]), reverse=reverse))


def dict_element_append(d: dict, key: str, value, unique=False) -> None:
  """ coerces key value in dict to list, than appends value to it
      Replaces safe_add_unique """
  key = str(key)
  if isinstance(value, list):
    for v in value: dict_element_append(d, key, v, unique)
  elif not d.get(key): d[key] = [value]
  elif isinstance(d[key], str): d[key] = [d[key], value]
  elif isinstance(d[key], list):
    if unique and value in d[key]: pass
    else: d[key] += [value]
  else: raise Exception(f"Unrecognized type: {type(d[key])}")


def dict_all_paths(d: dict) -> list:
  """Returns all paths in a dict as a list of strings"""
  result: list = []
  for key, value in d.items():
    if isinstance(value, dict):
      new_keys: list = dict_all_paths(value)
      result.append(key)
      for innerkey in new_keys: result.append(f'{key}/{innerkey}')
    else: result.append(key)
  return result
# endregion


# region working with yaml files: dict_to_yml, dict_from_yml, dict_sanitize
KEYS_FORCE_STRING = ['parent', '']
KEYS_DROP = ['api', 'adapi', 'AD', 'context', 'hide_attributes']
KEYS_FIRST = ['name', 'seid', 'path']


def dict_sanitize(data: dict | list, sort_keys=False) -> dict | list:
  """Convert nested complex data types for json.dumps or yaml.dumps"""
  def _sanitize_list(o) -> list:
    result = []
  
    for e in sorted(o, key=lambda x: str(x)):
      if _isdict(e): _ = _sanitize_dict(e)
      elif _islist(e): _ = _sanitize_list(e)
      elif _isnumber(e): _ = e
      else: _ = str(e) if e else None
      result.append(_)
    return result

  def _sanitize_dict(o) -> dict:
    result = {}
    if hasattr(o, 'as_dict'): d = o.as_dict()
    elif hasattr(o, 'data') and isinstance(o.data, dict): d = o.data
    else: d = dict(o)

    first_keys = [k for k in KEYS_FIRST if k in d]
    rest_keys = sorted(
      (k for k in d.keys() if k not in KEYS_FIRST and k not in KEYS_DROP),
      key=lambda k: str(k) if k else '?',
    )
    for k in first_keys + rest_keys:
      if k in KEYS_DROP: continue
      v = d.get(k)
      display_k = str(k) if k else '?'
      if display_k in KEYS_FORCE_STRING: _ = str(v)
      elif _isdict(v): _ = _sanitize_dict(v)
      elif _islist(v): _ = _sanitize_list(v)
      elif _isnumber(v): _ = v
      else: _ = str(v) if v else None
      result[display_k] = _
    return result

  def _isstring(o) -> bool:
    relatives = {type(o).__qualname__}
    relatives |= {c.__qualname__ for c in o.__class__.__mro__}
    return bool({'y2list', 'str', 'y2topic', 'y2path', 'ADBase'} & relatives)
  _islist = lambda o: not _isstring(o) and isinstance(o, (list, set))
  _isdict = lambda o: not _isstring(o) and (isinstance(o, (dict, defaultdict, UserDict)) or hasattr(o, 'as_dict') or (hasattr(o, 'data') and isinstance(o.data, dict)))
  _isnumber = lambda o: isinstance(o, (float, int))

  if _islist(data): return _sanitize_list(data)
  elif _isdict(data): return _sanitize_dict(data)
  else: raise ValueError(f"Unable to sanitize {data}")


# def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
#   return dumper.represent_dict(dict(enumerate(data)))
def _tuple_representer(dumper: Dumper, data: tuple) -> Node:
  return dumper.represent_dict(dict(enumerate(data)))

def dict_to_yml(filename: str | Path, data=None, sort_keys=False):
  class IndentedListDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
      return super(IndentedListDumper, self).increase_indent(flow, False)

  assert filename
  if not data: return
  redata = dict_sanitize(data, sort_keys=sort_keys)

  yaml.add_representer(defaultdict, SafeRepresenter.represent_dict)
  yaml.add_representer(UserDict, SafeRepresenter.represent_dict)
  yaml.add_representer(set, SafeRepresenter.represent_list)
  yaml.add_representer(tuple, _tuple_representer)

  with open(filename,'w+', encoding='utf-8') as f:
    try: yaml.dump(redata, f, indent=2, Dumper=IndentedListDumper, sort_keys=False, width=2147483647)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
      with open(str(filename) + '_error.txt', 'w+', encoding='utf-8') as ferr: ferr.write(error)


YML_BARE_INCLUDE = re.compile(r"^!include\s+\S.*$", re.MULTILINE)
YML_BARE_KEY = '__include_'


def dict_from_yml(filename: str | Path) -> dict:
  filename = full_path(filename)
  dir_stack: list[Path] = [filename.parent]
  bare_seq = iter(range(1 << 30))

  class YmlLoader(FullLoader): pass
    # def __init__(self, stream: Any) -> None:
    #   super().__init__(stream)


  def yml_keyed(text: str) -> str:                                                         # `!include` alone on a line has no
    def key(m): return f'{YML_BARE_KEY}{next(bare_seq)}: {m.group()}'                      # key, which YAML rejects next to
    return YML_BARE_INCLUDE.sub(key, text)                                                 # other keys; give it a private one

  def yml_merged(data: Any) -> Any:                                                        # ... and merge what it loaded into
    if not isinstance(data, dict): return data                                             # the document that included it
    merged: dict = {}
    for k, v in data.items():
      if isinstance(k, str) and k.startswith(YML_BARE_KEY): merged.update(v)
      else: merged[k] = v
    return merged

  def yml_load(text: str) -> Any: return yml_merged(yaml.load(yml_keyed(text), Loader=YmlLoader))

  def yml_include(loader: FullLoader, node: Node) -> Any:
    fn = full_path(loader.construct_scalar(node), dir_stack[-1])

    dir_stack.append(fn.parent)

    try:
      with open(fn, "r", encoding='utf-8') as f:
        if fn.suffix.lower().endswith('.json'): return json.load(f)                        # JSON (tabs/escapes YAML rejects)
        return yml_load(f.read())
    finally: dir_stack.pop()

  def yml_secret(loader: FullLoader, node: Node) -> Any: return Vault.get(loader.construct_scalar(node))

  YmlLoader.add_constructor("!include", yml_include)
  YmlLoader.add_constructor("!secret", yml_secret)

  with open(filename, encoding='utf-8') as f: data = yml_load(f.read())

  return dict(data or {})


  # with open(filename, encoding='utf-8') as f: return dict(yaml.load(f, Loader=yaml.FullLoader))


def dict_to_json(filename: str | Path, data=None, indent=2):
  assert filename
  if not data: return
  with open(filename, 'w', encoding='utf-8') as f:
    try: json.dump(data, f, indent=indent, ensure_ascii=False, default=str)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(data)}\n\n"
      with open(str(filename)+'_error.txt', 'w', encoding='utf-8') as ferr: ferr.write(error)


def dict_from_json(filename: str | Path):
  with open(filename, encoding='utf-8') as f: return json.load(f)

## _________Code below has deviated from the golden rule                                                  
## !! templates are simple inline functtions that return lists, dicts or scalars to be merged into dicts.
def dict_template_populate(o, data: dict = {}, excludes:list = []) -> dict:
  _ = template_populate(o, data, excludes)
  return _ if isinstance(_, dict) else {}


def template_populate(o, data: dict = {}, excludes:list = []) -> Any:
  def __tp(o: dict | str, data: dict) -> Any:
    result: Any = None
    if not data: data = {}

    if not o: return None
    if isinstance(o, dict):
      result = {}
      for k, old in o.items():
        if k in excludes or inspect.isfunction(old): new = old
        else: new = __tp(old, o | data)
        result[k] = new
    elif isinstance(o, list):
      result = []
      for old in o:
        new = __tp(old, data)
        result.append(new)
    elif isinstance(o, (int, bool, float)): result = o
    elif inspect.isfunction(o): result = o
    else:
      if str(o) == 'DEL': result = None
      elif '$' in str(o): 
        _ = str(Template(str(o)).safe_substitute(data))
        if _[0] == '[' and _[-1] == ']':
          result = []
          _ = _[1:-1]
          for element in _.split(','):
            element = element.strip()
            if element.isdecimal(): element = int(element)
            elif element.isnumeric(): element = float(element)
            result.append(element)
        else: result = _
      else: result = o
    return result

  if isinstance(o, dict): _ = o.get('data', {}) | o
  else: _ = str(o)
  return __tp(_, data)


class JinjaEnvironment(SandboxedEnvironment, NativeEnvironment):
  """Jinja templates with native values and gppu's formatting helpers."""

  def __init__(self, **options):
    super().__init__(undefined=StrictUndefined, autoescape=False, **options)
    helpers = {
      'safe_int': safe_int, 'safe_float': safe_float, 'safe_list': safe_list,
      'safe_timedelta': safe_timedelta, 'dict_sanitize': dict_sanitize,
      'pretty_timedelta': pretty_timedelta, 'pfy': pfy, 'slugify': slugify,
    }
    self.filters.update(helpers)
    self.globals.update(helpers)


@cache
def _jinja_compile(template: str):
  return JinjaEnvironment().from_string(template)


def jinja_template(template: str, /, **data) -> Any:
  """Render Jinja to a string, scalar, list or mapping; missing inputs raise."""
  value = _jinja_compile(template).render(**data)
  if isinstance(value, StrictUndefined): str(value)
  return value
# endregion


# region Time helpers
def now_str(): return datetime.now().strftime("%Y%m%d.%H%M%S")
def now_ts(): return datetime.now().timestamp()

def timestamp(): return datetime.now().strftime("%y%m%d-%H%M")
def datestamp(): return datetime.now().strftime("%y%m%d")

def prepend_datestamp(path, separator=" ") -> Path:
  datestamp_str = datestamp()  
  _ = Path(path)
  return _.parent / f"{datestamp_str}{separator}{_.name}"

def append_timestamp(path, separator=" ") -> Path:
  timestamp_str = timestamp()
  _ = Path(path)
  return _.parent / f"{_.stem}{separator}{timestamp_str}{_.suffix}"


def pretty_timedelta(ts) -> str:
  delta = now_ts() - ts
  seconds = int(delta)
  days, seconds = divmod(seconds, 86400)
  hours, seconds = divmod(seconds, 3600)
  minutes, seconds = divmod(seconds, 60)
  if days > 0: return '%dd %dh %dm %ds' % (days, hours, minutes, seconds)
  elif hours > 0: return '%dh %dm %ds' % (hours, minutes, seconds)
  elif minutes > 0: return '%dm %ds' % (minutes, seconds)
  else: return '%ds' % (seconds,)
# endregion


# region Human-readable formatters

def format_size(size: int | float) -> str:
  """Format byte count as '0 B', '1.5 KB', '2.3 MB', '4.5 GB', '7.8 TB'.

  Powers-of-1024 (binary). One decimal for KB+, two for TB.
  """
  size = float(size)
  if size < 1024:                  return f"{int(size)} B"
  if size < 1024 ** 2:             return f"{size / 1024:.1f} KB"
  if size < 1024 ** 3:             return f"{size / 1024 ** 2:.1f} MB"
  if size < 1024 ** 4:             return f"{size / 1024 ** 3:.1f} GB"
  return f"{size / 1024 ** 4:.2f} TB"


def format_duration(seconds: int | float) -> str:
  """Format a duration as '0s' / '5s' / '12m 30s' / '2h 5m'.

  Input is seconds (use ``ms / 1000`` for millisecond inputs).  Returns
  ``'-'`` for negative values; ``0`` formats as ``'0s'`` so callers using
  this for uptime get a legitimate zero rather than a placeholder.
  """
  seconds = float(seconds)
  if seconds < 0: return "-"
  if seconds < 60: return f"{seconds:.0f}s"
  if seconds < 3600:
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {int(s)}s"
  h, rem = divmod(seconds, 3600)
  m, _ = divmod(rem, 60)
  return f"{int(h)}h {int(m)}m"


def format_since(when) -> str:
  """Compact "time since" — '5s', '5m', '2h', '3d', '4w', '6mo', '2y'.

  Accepts ISO-8601 string, ``datetime``, or epoch seconds (int/float).
  Returns empty string on parse failure.  Negative deltas (future timestamps)
  return ``'0s'``.
  """

  dt = None
  if isinstance(when, datetime):
    dt = when
  elif isinstance(when, (int, float)):
    dt = datetime.fromtimestamp(float(when), tz=timezone.utc)
  elif isinstance(when, str):
    s = when.strip()
    if not s: return ""
    if s.endswith('Z'): s = s[:-1] + '+00:00'
    try: dt = datetime.fromisoformat(s)
    except ValueError: return ""
  else:
    return ""

  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)

  secs = int((datetime.now(timezone.utc) - dt).total_seconds())
  if secs < 0:    return "0s"
  if secs < 60:   return f"{secs}s"
  mins = secs // 60
  if mins < 60:   return f"{mins}m"
  hrs = mins // 60
  if hrs < 24:    return f"{hrs}h"
  days = hrs // 24
  if days < 7:    return f"{days}d"
  if days < 30:   return f"{days // 7}w"
  if days < 365:  return f"{days // 30}mo"
  return f"{days // 365}y"
# endregion


# region prettify and slugify
def pfy(object) -> str: return "\n"+pprint.pformat(object, indent=4, width=40, compact=True)
def slugify(o) -> str:
  """Converts any object to string, then slugifies it"""
  return re.sub(r'[^a-zA-Z0-9_]', '_', str(o).lower())
# endregion




# region Async helpers
def sync(func: Callable) -> Callable:
  """Wrapper to call async functions without await from synchronous code."""
  @wraps(func)
  def wrapper(*args, **kwargs):
    coro = func(*args, **kwargs)
    try:
      loop = asyncio.get_running_loop()
    except RuntimeError:
      return asyncio.run(coro)
    return loop.create_task(coro)
  return wrapper
# endregion


# region PCP - Pretty Colored Print and colorize - utility
class _TColorHack(type):
  def __getitem__(cls, key): return getattr(cls, str(key), None)
  def __contains__(cls, key): return hasattr(cls, str(key))

  def print(cls):
    l = []
    for name in dir(cls):
      colorcode = getattr(cls, name)
      if isinstance(colorcode, str): l.append(colorcode)
      l.append(name)
    print(_colorize_list(l))


class TColor(metaclass=_TColorHack):
  NONE = '0m'             # No color (text)
  DIM = '38;5;8;1'        # Dim gray (text)
  BRIGHT = '36;1'         # Bright cyan (text)
  BW = '38;5;15;1'        # Bright white (text)
  DW = '38;5;7;1'         # Dark white (text)
  INFO = '34;1'           # Bright blue (text, for info messages)
  WHITE = '0;30;47'       # Black on White (background)
  YELLOW = '0;30;43'      # Black on Yellow (background)
  RED = '0;30;41'         # Black on Red (background)
  BLUE = '0;30;44'        # Black on Blue (background)
  GREEN = '0;30;42'       # Black on Green (background)

  GRAY0 = '38;5;237'      # Darkest gray (text)
  GRAY1 = '38;5;238'      # Gray (text)
  # GRAY2 = '38;5;239'      # Gray (text)
  GRAY2 = '38;5;243'      # Gray (text)
  GRAY3 = '38;5;246'      # Gray (text)
  GRAY4 = '38;5;249'      # Lightest gray (text)

  BY = '38;5;11;1'        # Bright yellow (text)
  DY = '38;5;3;1'         # Dark yellow (text)
  BG = '38;5;10;1'        # Bright green (text)
  DG = '38;5;2;1'         # Dark green (text)
 
  # BB = '3;30;44'          # Black on Blue (background)
  DB = '38;5;4;1'         # Dark blue (text)

  BC = '38;5;6;1'         # Bright cyan (text)
  DC = '38;5;14;1'        # Dark cyan (text)
  BM = '38;5;13;1'        # Bright magenta (text)
  DM = '38;5;5;1'         # Dark magenta (text)
  BR = '38;5;9;1'         # Bright red (text)
  DR = '38;5;1;1'         # Dark red (text)
  BP = '38;5;129;1'       # New: Bright purple (text)
  DP = '38;5;90;1'        # New: Dark purple (text)
  BO = '38;5;130;1'       # New: Bright orange (text)
  DO = '38;5;130;1'       # New: Dark orange (text)
  PINK = '38;5;200;1'     # New: Bright pink (text)
  DPINK = '38;5;132;1'    # New: Dark pink (text)
  BGOLD = '38;5;220;1'    # New: Bright gold (text)
  DGOLD = '38;5;178;1'    # New: Dark gold (text)

  ORANGE = BO   # New: Bright orange (text)
  PURPLE = BP   # New: Bright purple (text)

  WRED = '0;37;41'        # White on Red (background)
  WBLUE = '0;37;44'       # White on Blue (background)
  WGREEN = '0;37;42'      # White on Green (background)
  WGRAY = '0;30;47'       # Black on Light Gray (background)
  WPINK = '0;30;45'       # Black on Pink (background)
  WPURPLE = '0;37;45'     # White on Purple (background)
  #WYELLOW = '0;37;43'     # White on Yellow (background)
  WYELLOW = '7;49;93'     # White on Yellow (background)


def pcp(*a: str | List[Any] | Tuple[Any, ...], **kw: Any) -> str:
  """
  Pretty colored print. Returns: colored string
  
  Parameters:
    verbose: adds pfy(kwargs) to output
    silent: suppresses local print output
    
  """
  if len(a) == 1 and isinstance(a[0], tuple): a = tuple(a[0])
  out: str = ""
  verbose = kw.pop('verbose', False)
  silent = kw.pop('silent', False)
  level = kw.pop('level', None)
  
  if 'msg' in kw:
    msg = kw.get('msg')
    out = _colorize_log(msg=msg, level=level)
    if a: out += _colorize_list(a) # type: ignore
  else: out = _colorize_list(a) # type: ignore
  if kw and verbose: out += pfy(kw)

  # if not silent: print(out)
  if not out.endswith('\u001b[0m'): out = out + '\u001b[0m' # Check if color reset is already present
  return out


_remove_prefixes = lambda s, prefixes: next((s.removeprefix(prefix) for prefix in prefixes if s.startswith(prefix)), s)
_SHORTEN_BY_PREFIX = ['process_', '_cb_']
_IGNORE_FUNCTIONS = ['dpcp', 'trace', 'pcp', 'Trace', 'Info', 'Debug', 'Warn', 'Error', '_LogColorizer', '_PlainFormatter']
_SEVERITY_COLORS = {'Error': 'WRED', 'Warn': 'WYELLOW', 'Info': 'WBLUE', 'Debug': 'GRAY4', None: 'WPURPLE'}
def dpcp(*a: Any, conditional: Optional[bool] = None, rules: Dict[str, bool] = {}, no_prefix: bool = False, severity: Optional[str] = None, **kw: Any) -> str | None:
  """ Version of pcp that adds info on where it was called from """
  def is_traced(name : Optional[str] = None) -> bool:
    if not conditional: return True
    if not name or name not in rules: return rules.get('all', False)
    else: return rules.get(name, False)

  def is_ignored(f, fi) -> bool:
    if 'python' in fi.filename: return True # !!! Ignoring all python3 libraries
    elif fi.function in _IGNORE_FUNCTIONS: return True
    elif 'self' in f.f_locals and f.f_locals['self'].__class__.__name__ in _IGNORE_FUNCTIONS: return True
    return False

  print = lambda *a, **kw: None

  if not conditional and rules: conditional = True
  frame = inspect.currentframe()
  if frame is None: return None
  frame_info = inspect.getframeinfo(frame)
  func_name = frame_info.function
  filename = frame_info.filename

  frame = frame.f_back
  while frame and frame.f_back:
    frame = frame.f_back
    frame_info = inspect.getframeinfo(frame)
    filename = frame_info.filename
    func_name = frame_info.function
    if not is_ignored(frame, frame_info): break

    func_name = _remove_prefixes(func_name, _SHORTEN_BY_PREFIX)

  if frame is None: print(f"\tframe is None"); return None

  if not is_traced(func_name): print(f"\tis_traced({func_name}) is False"); return None
  module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
  if not is_traced(module) or not is_traced(f"{module}.{func_name}"): print(f"\tis_traced({module}.{func_name}) is False"); return None

  if 'self' in frame.f_locals: 
    if not is_traced(class_name := frame.f_locals["self"].__class__.__name__): print(f"\tis_traced({class_name}) is False"); return None
    if not is_traced(f"{class_name}.{func_name}"): print(f"\tis_traced({class_name}.{func_name}) is False"); return None
    _ = ['GRAY0', f"{class_name}.", 'GRAY1', f".{func_name}"]
  else: _ = ['GRAY1', f".{func_name}"]
  _ += ['NONE']

  if severity: _ = [_SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[None]), severity] + _
  if no_prefix: _ = list(a)
  else: _ += list(a)

  result = pcp(*_, **kw)
  # Never return None - return empty string instead to prevent logging issues
  return result if result is not None else ''


def _colorize_log(msg, level=None, *args) -> str:
  if isinstance(msg, tuple): msg = _colorize_list(msg) # type: ignore
  elif level:
    if level in ['CRITICAL', 'ERROR']: c1, c2 = 'BR', 'BRIGHT'
    elif level in ['WARN', 'WARNING']: c1, c2 = 'BY', 'BRIGHT'
    elif level in ['INFO']: c1, c2 = 'BLUE', 'INFO'
    elif level in ['DEBUG']: c1, c2 = 'DIM', 'DIM'
    else: c1, c2 = 'DIM', 'INFO'
    msg_list = [c1, level, c2, msg] + list(args)
    msg = _colorize_list(msg_list)
  return msg


def _colorize_list(l: List[Union[str, TColor]]) -> str:
  """ Colorizes list of strings. Strings separated with space unless start with . or / """
  result: List[str] = []
  colorcode = None

  for e in [e for e in l if e]:
    if isinstance(e, TColor): colorcode = e; continue
    e = str(e)
    if e[0] in "./": separator = ''; e = e[1:]
    else: separator = ' '

    if e in TColor: colorcode = TColor[e]; continue
    elif colorcode: elem = _colorize(text=str(e), colorcode=colorcode) # type: ignore
    else: elem = str(e)

    if e[0] in "./" and result: result += [elem]
    elif not result: result += [elem]
    else: result += [separator+elem]
    
  return ''.join(result)  # Reset color at the end


def _colorize(text: str, colorcode:str, fmt=None):
  """
    Print a string in a given color.
    fmt: accepts formatting syntax with < and > anchors
  """
  # ESC = '\u001b'
  ESC = '\033'  # ANSI escape code for terminal colors
  NOP = ESC + '[0m'
  if (color := colorcode):
    if color[0] == ESC and color[1] == '[': pass
    elif color[0] == ESC: color = ESC + '[' + color[1:]
    else: color = ESC + '[' + color

    if color[-1] == 'm': pass
    else: color += 'm'
  else: color = NOP
  right, pad = False, ''
  text = str(text)
  if fmt:
    if fmt[0] in "<>": right = fmt[0] == '>'; fmt = fmt[1:]
    maxlen = safe_int(fmt)

    text = text[-maxlen:] if right else text[0:maxlen]
    if (l := len(text)) < maxlen: pad = ' ' * (maxlen - l)

  text = color + text + NOP
  return pad + text if right else text + pad



_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _traced(record: logging.LogRecord) -> bool:
  if record.levelno != logging.DEBUG: return True
  function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
  names = [function, record.module, f'{record.module}.{function}']
  if class_name := getattr(record, 'gppu_class', ''):
    names += [class_name, f'{class_name}.{function}']
  return all(TRACE_RULES[name] if name in TRACE_RULES else TRACE_RULES.get('all', False) for name in names)


def _fmt(record: logging.LogRecord, *, no_prefix: bool = False) -> str:
  args = list(record.gppu_args) if hasattr(record, 'gppu_args') else [record.getMessage()]
  if not no_prefix:
    function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
    class_name = getattr(record, 'gppu_class', '')
    caller = f'{class_name}.{function}' if class_name else function
    severity = 'Warn' if record.levelno == logging.WARNING else record.levelname.title()
    color = _SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[None])
    args = [color, severity, 'GRAY1', caller, 'NONE'] + args
  text = pcp(*args)
  if record.exc_info:
    text += '\n' + logging.Formatter().formatException(record.exc_info)
  if record.stack_info: text += '\n' + record.stack_info
  return text


class _LogColorizer(logging.Formatter):
  def format(self, record: logging.LogRecord) -> str:
    return _fmt(record)
# endregion


# region Logger
# ^~            Logger                                            
TRACE_RULES: dict = {}

_log_root = logging.getLogger('gppu')
_log_root.setLevel(logging.DEBUG)
_logger = _log_root


class _EmptyMessageFilter(logging.Filter):
  def filter(self, record: logging.LogRecord) -> bool:
    return _traced(record) and bool(record.getMessage().strip() or record.exc_info)


_sh = logging.StreamHandler(sys.stderr)
_sh.setLevel(logging.DEBUG)
_sh.setFormatter(_LogColorizer())
_sh.addFilter(_EmptyMessageFilter())
_logger.addHandler(_sh)


class _PlainFormatter(logging.Formatter):
  def format(self, record: logging.LogRecord) -> str:
    return _ANSI.sub('', _fmt(record, no_prefix=True))


# File handlers live on the shared parent so pre-existing mixins receive them.
_file_handlers: dict[str, logging.Handler] = {}


def enable_file_logging(name: str | None = None, log_dir: str | Path | None = None,
                        level: int = logging.DEBUG) -> Path:
  """Mirror logs to Env's explicit `log_file`, or an explicit name + log_dir.

  Env enables this automatically when YAML declares `log_file`. No directory
  or filename is inferred. Creation errors propagate to the caller.
  """
  if log_dir is not None:
    if not name: raise ValueError('File logging with log_dir requires a name')
    path = full_path(Path(log_dir) / f'{name}.log')
  else:
    value = Env.glob('log_file')
    if not isinstance(value, str) or not value.strip():
      raise ValueError('File logging requires an explicit log_file in configuration')
    path = full_path(value)
  path.parent.mkdir(parents=True, exist_ok=True)
  key = str(path)
  if key in _file_handlers:
    return path
  from logging.handlers import RotatingFileHandler
  fh = RotatingFileHandler(path, maxBytes=4_000_000, backupCount=5, encoding='utf-8')
  fh.setLevel(level)
  fh.setFormatter(_PlainFormatter())
  fh.addFilter(_EmptyMessageFilter())
  _log_root.addHandler(fh)
  _file_handlers[key] = fh
  return path


def file_log(msg: str, *args, level: int = logging.INFO) -> None:
  """Emit a line only to gppu's file handler(s), bypassing the console handler.

  For Textual TUI apps whose visible "console" is the on-screen panel: this
  mirrors panel lines into the log file without writing to stderr (which would
  corrupt the live TUI). No-op when file logging isn't enabled.
  """
  if not _file_handlers:
    return
  record = _logger.makeRecord(_logger.name, level, '(app)', 0,
                              _ANSI.sub('', pcp(msg, *args)), (), None,
                              func='file_log', extra={'gppu_args': (msg, *args)})
  for h in _file_handlers.values():
    if record.levelno >= h.level:
      h.handle(record)


def _init_logger_base(name: str = 'gppu', trace_rules: dict | None = None) -> None:
  """Initialize global logger with a specific name and optional trace rules."""
  global _logger
  if trace_rules is not None:
    trace_rules = dict(trace_rules)
    TRACE_RULES.clear()
    TRACE_RULES.update(trace_rules)
  _logger = _log_root if name == 'gppu' else _log_root.getChild(name)

init_logger = _init_logger_base


def _log(level: int, args: tuple, logger, options: dict) -> None:
  target = _logger if logger is None else logger
  if not target.isEnabledFor(level): return
  frame = inspect.currentframe().f_back.f_back
  extra = dict(options.pop('extra')) if 'extra' in options else {}
  extra['gppu_args'] = args
  extra['gppu_class'] = type(frame.f_locals['self']).__name__ if 'self' in frame.f_locals else ''
  del frame
  stacklevel = options.pop('stacklevel') if 'stacklevel' in options else 1
  target.log(level, _ANSI.sub('', pcp(*args)), extra=extra, stacklevel=stacklevel + 2, **options)


def Debug(*a, logger=None, **kw): _log(logging.DEBUG, a, logger, kw)
def Info(*a, logger=None, **kw): _log(logging.INFO, a, logger, kw)
def Warn(*a, logger=None, **kw): _log(logging.WARNING, a, logger, kw)
def Error(*a, logger=None, **kw): _log(logging.ERROR, a, logger, kw)
@sync
async def Dump(filename: str, data={}, **kw) -> None:
  """ Saves data object to yml file in trace folder """
  if '.' not in filename or not filename.endswith('.yml'): filename += '.yml'
  if Logger.trace_folder:
    filename = f"{Logger.trace_folder}/{filename}"
  dict_to_yml(filename=filename, data=data)


# endregion


# region Environment
def _config_changes(before: dict, after: dict, prefix: str = '') -> frozenset[str]:
  changed = set()
  for key in before.keys() | after.keys():
    path = f'{prefix}/{key}' if prefix else str(key)
    if key not in before or key not in after:
      changed.add(path)
    elif isinstance(before[key], dict) and isinstance(after[key], dict):
      changed.update(_config_changes(before[key], after[key], path))
    elif isinstance(before[key], list) and isinstance(after[key], list):
      if json.dumps(before[key], sort_keys=True) != json.dumps(after[key], sort_keys=True): changed.add(path)
    elif type(before[key]) is not type(after[key]) or before[key] != after[key]:
      changed.add(path)
  return frozenset(changed)


class Env:
  data: dict[str, Any] = {}
  initialized: bool = False
  changed_paths: frozenset[str] = frozenset()
  _listeners: list[tuple[str, Callable[[frozenset[str]], None]]] = []

  name: str
  app_path: Path

  home: Path = Path.home()
  user: str = getpass.getuser()
  os: OSType = detect_os()

  _logger: logging.Logger

  @staticmethod
  def _load_dict(d: dict) -> None:
    s = json.dumps(d)
    data = json.loads(Template(s).safe_substitute())
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    if 'trace_rules' in data and not isinstance(data['trace_rules'], dict):
      raise TypeError('trace_rules must be a mapping')
    if 'log_file' in data and (not isinstance(data['log_file'], str) or not data['log_file'].strip()):
      raise ValueError('File logging requires an explicit log_file in configuration')
    changed = _config_changes(Env.data, data)
    if Env.initialized and not changed:
      Env.changed_paths = changed
      return
    if 'trace_rules' in Env.data and 'trace_rules' not in data: TRACE_RULES.clear()
    if Env.initialized or Env.data: Env.reset(); Logger.Info('INFO', 'Environment', 'WRED', 'reset()')
    Env.data = data
    Env.initialized = True
    if 'trace_rules' in Env.data:
      rules = Env.glob('trace_rules')
      if not isinstance(rules, dict): raise TypeError('trace_rules must be a mapping')
      TRACE_RULES.clear()
      TRACE_RULES.update(rules)
    if 'log_file' in Env.data: enable_file_logging()
    Env.changed_paths = changed
    for path, callback in tuple(Env._listeners):
      relevant = frozenset(key for key in changed if not path or key == path
                           or key.startswith(path + '/') or path.startswith(key + '/'))
      if relevant: callback(relevant)

  @staticmethod
  def reset() -> None:
    for handler in tuple(_file_handlers.values()):
      _log_root.removeHandler(handler)
      handler.close()
    _file_handlers.clear()
    Env.data = {}
    Env.initialized = False
    Env.changed_paths = frozenset()

  @staticmethod
  def on_change(callback: Callable[[frozenset[str]], None], path: str = '') -> Callable[[], None]:
    """Observe changed slash paths after loading; return a callable to unsubscribe.

    Callbacks are synchronous. The consumer decides how to apply each change.
    Registrations survive configuration reloads and reset().
    """
    if inspect.iscoroutinefunction(callback): raise TypeError('configuration change callbacks must be synchronous')
    entry = (path.strip('/'), callback)
    Env._listeners.append(entry)
    def unsubscribe():
      if entry in Env._listeners: Env._listeners.remove(entry)
    return unsubscribe

  @staticmethod
  def update_config(data: dict, path: str = '') -> None:
    """Replace one configuration subtree; an empty path replaces the whole config."""
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    if not path:
      Env._load_dict(data)
      return
    updated = deepcopy(Env.data)
    node = updated
    *parents, key = path.split('/')
    for parent in parents:
      if parent not in node: node[parent] = {}
      node = node[parent]
      if not isinstance(node, dict): raise TypeError(f'configuration parent is not a mapping: {path}')
    node[key] = data
    Env._load_dict(updated)

  @staticmethod
  async def from_mqtt(config: dict) -> None:
    """Load exact topics into their declared Env paths through gppu's MQTT transport.

    config contains connection and topics (MQTT topic -> Env path). Disconnect
    once all topics arrive. Apps needing updates use their own mqtt_config().
    """
    from .iot import _MqttConfig
    await _MqttConfig(config).run()

  @staticmethod
  def glob(path, default=None) -> Any: return Env.data if path == '' else deepget(path, Env.data, default=default)
  @staticmethod
  def glob_int(path, default: int = 0) -> int: return deepget_int(path, Env.data, default=default)
  @staticmethod
  def glob_list(path, default=[]) -> list: return deepget_list(path, Env.data, default=default)
  @staticmethod
  def glob_dict(path, default={}) -> dict: return Env.data if path == '' else deepget_dict(path, Env.data, default=default)
  @staticmethod
  @sync
  async def dump():
    Dump('Env.data', Env.data)
    return await asyncio.sleep(0)  # Make it truly async

  @staticmethod
  def from_dict(d: dict) -> None:
    """Initialize Env from a dict. A ``topology`` key (a yaml path) is loaded as
    the base data; ``tunables`` (an inline dict) and the remaining keys override
    it — mirroring Y2's Environment loader. Without ``topology`` the dict itself
    is the data (back-compatible)."""
    config = dict(d)
    topology = config.pop('topology', None)
    tunables = config.pop('tunables', None)
    data = dict_from_yml(topology) if topology else {}
    if isinstance(tunables, dict): data.update(tunables)
    data.update(config)
    Env._load_dict(data)

  @staticmethod
  def from_env(name: Optional[str] = None, app_path: Optional[Path] = None) -> None:
    """Initialize Env from name + app_path, resolving config file and loading YAML."""
    import __main__
    Env._main_file = Path(getattr(__main__, '__file__', 'app')).resolve()
    Env._main_dir = Env._main_file.parent

    # Under PyInstaller __main__.__file__ resolves to __main__; use exe name instead
    if name:
      Env.name = name
    elif getattr(sys, 'frozen', False):
      Env.name = Path(sys.executable).stem
    else:
      Env.name = Env._main_file.stem
    Env.app_path = Env._resolve_app_path(app_path)
    Env.config_file = Env._config_file()

    Env._logger = _logger.getChild(Env.name)
    for attr_name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)):
      setattr(Env, attr_name, staticmethod(partial(fn, logger=Env._logger)))

    config_data = dict_from_yml(Env.config_file)
    Env.from_dict(config_data)   # resolves a `topology:` key if the config has one

  @staticmethod
  def _resolve_app_path(app_path: Optional[Path] = None) -> Path:
    if not app_path: return Env._main_dir
    if app_path.is_absolute(): return app_path
    # Walk up from script location to find the relative path
    parent = Env._main_dir
    while parent != parent.parent:
      candidate = parent / app_path
      if candidate.exists(): return candidate
      parent = parent.parent
    return Env._main_dir / app_path

  @staticmethod
  def _config_file() -> Path:
    """``<name>.yaml`` then ``config.yaml``, searched from ``app_path`` upward —
    so a service in a subdir (e.g. /app/brultech) finds the suite's /app/config.yaml."""
    names = (Path(Env.name).with_suffix('.yaml').name, 'config.yaml')
    for parent in (Env.app_path, *Env.app_path.parents):
      for name in names:
        candidate = parent / name
        if candidate.exists(): return candidate
    raise FileNotFoundError(f"Config ({' or '.join(names)}) not found walking up from '{Env.app_path}'")

# Global aliases for Env.glob* methods
glob = Env.glob
glob_int = Env.glob_int
glob_list = Env.glob_list
glob_dict = Env.glob_dict
# endregion


# region Vault / Secrets
# Vault is a static facade over a VaultProvider chain. The default chain assembles
# VaultProviderOSEnviron + VaultProviderAzure, auto-detected from env
# (AZURE_KEYVAULT_NAME) on first use. Override the active provider via
# Vault.provider_set(...). Class names follow the subject-hierarchy convention:
# VaultProvider, VaultProviderAzure, etc.

class VaultProvider:
  """Abstract secret-backend provider. Subclass and override get; override set/list if writable/enumerable."""
  def get(self, name: str) -> str | None: raise NotImplementedError
  def set(self, name: str, value: str) -> None: raise NotImplementedError(f"{type(self).__name__} is read-only")
  def list(self) -> list[str]: raise NotImplementedError(f"{type(self).__name__} does not support listing")


class VaultProviderOSEnviron(VaultProvider):
  """Reads from environment variables: SECRET_<NAME> (hyphens → underscores, uppercased). Read-only."""

  def get(self, name: str) -> str | None: return os.environ.get('SECRET_' + name.upper().replace('-', '_'))

  def list(self) -> list[str]:
    prefix = 'SECRET_'
    return sorted(k[len(prefix):].lower().replace('_', '-') for k in os.environ if k.startswith(prefix))


class VaultProviderAzure(VaultProvider):
  def __init__(self, vault_name: str):
    self._vault_name = vault_name
    self._client = None

  def _ensure_client(self):
    if self._client is None:
      from azure.identity import DefaultAzureCredential
      from azure.keyvault.secrets import SecretClient
      self._client = SecretClient(
        vault_url=f"https://{self._vault_name}.vault.azure.net",
        credential=DefaultAzureCredential())
    return self._client

  def get(self, name: str) -> str | None:
    try: return self._ensure_client().get_secret(name).value
    except Exception: return None

  def set(self, name: str, value: str) -> None:
    self._ensure_client().set_secret(name, value)

  def list(self) -> list[str]:
    return [s.name for s in self._ensure_client().list_properties_of_secrets()]



class Vault:
  """Static facade for secret operations.

  Resolution order on get: OSEnviron (SECRET_<NAME> env var) → persistent provider.
  Writes go to the persistent provider (Vault.provider). OSEnviron is read-only.
  """

  _cache: dict[str, str] = {}
  _provider: VaultProvider | None = None
  _env_provider: VaultProvider = VaultProviderOSEnviron()

  @staticmethod
  def provider_set(provider: VaultProvider | None) -> None:
    """Set the active persistent provider. Pass None to clear and re-detect from env on next use."""
    Vault._provider = provider
    Vault._cache.clear()

  @staticmethod
  def provider() -> VaultProvider:
    """Return the active persistent provider, auto-detecting from env on first call.

    Falls back to VaultProviderOSEnviron when AZURE_KEYVAULT_NAME is not set.
    """
    if Vault._provider is None:
      Vault._provider = Vault._detect()
    return Vault._provider

  @staticmethod
  def _detect() -> VaultProvider:
    """AZURE_KEYVAULT_NAME → VaultProviderAzure; else env-var fallback."""
    vault_name = os.environ.get('AZURE_KEYVAULT_NAME')
    if vault_name: return VaultProviderAzure(vault_name)
    return Vault._env_provider

  @staticmethod
  def get(name: str) -> str:
    if name in Vault._cache: return Vault._cache[name]

    checked: list[str] = [type(Vault._env_provider).__name__]
    val = Vault._env_provider.get(name)

    p = Vault.provider()
    if val is None and p is not Vault._env_provider:
      val = p.get(name)
      checked.append(type(p).__name__)

    if val is None:
      raise ValueError(f"!secret '{name}' not found (checked {', '.join(checked)})")

    Vault._cache[name] = val
    return val

  @staticmethod
  def create(name: str, value: str, designation: str | None = None) -> None:
    """Create a new secret. Raises if name already exists — use update to overwrite.

    designation: optional suffix appended as '-<designation>' (kebab-lower) to disambiguate
    when the base name collides with an existing secret.
    """
    if Vault._exists(name) and designation:
      name = f"{name}-{designation.lower().replace('_', '-')}"
    if Vault._exists(name):
      raise ValueError(f"Secret '{name}' already exists. Use Vault.update to overwrite.")
    Vault._write(name, value)

  @staticmethod
  def update(name: str, value: str, create: bool = False) -> None:
    """Update an existing secret (creates a new version).

    Raises if the name does not exist, unless create=True — in which case it falls through to create.
    """
    if not Vault._exists(name) and not create:
      raise ValueError(f"Secret '{name}' does not exist. Pass create=True to add it, or use Vault.create.")
    Vault._write(name, value)

  @staticmethod
  def _exists(name: str) -> bool:
    return Vault.provider().get(name) is not None

  @staticmethod
  def _write(name: str, value: str) -> None:
    Vault.provider().set(name, value)  # raises NotImplementedError if provider is read-only
    Vault._cache[name] = value

  @staticmethod
  def list() -> list[str]:
    """List secret names available from the active provider.

    Union of env-var fallback names + persistent provider names; sorted, deduped.
    """
    names = set(Vault._env_provider.list())
    p = Vault.provider()
    if p is not Vault._env_provider:
      try: names.update(p.list())
      except NotImplementedError: pass
    return sorted(names)

  @staticmethod
  def cache_clear() -> None:
    Vault._cache.clear()
# endregion


# region Mixins
class _mixin: pass


class mixin_Config(_mixin):
  _my: dict[str, Any] = {}

  def _config_from_key(self, key: str) -> None: self._my.update(Env.glob_dict(key))
  def _config_copy(self, other: mixin_Config) -> None: self._my = dict(other._my)
  def _config_from_dict(self, d: dict) -> None: self._my = deepcopy(d)
  def _config_from_env(self) -> None: self._my = deepcopy(Env.data)

  def my(self, path, default=None) -> Any: return deepget(path, self._my, default=default)
  def my_int(self, path, default: int = 0) -> int: return deepget_int(path, self._my, default=default)
  def my_float(self, path, default: float = float('nan')) -> float: return deepget_float(path, self._my, default=default)
  def my_list(self, path, default: list = []) -> list: return deepget_list(path, self._my, default=default or [])
  def my_dict(self, path, default: dict = {}) -> dict: return deepget_dict(path, self._my, default=default or {})


class Logger:
  """Namespace wrapper exposing logging helpers."""
  trace_folder: str = '.'
  trace_rules: dict = TRACE_RULES

  Debug = staticmethod(Debug)
  Info = staticmethod(Info)
  Warn = staticmethod(Warn)
  Error = staticmethod(Error)
  @staticmethod
  def Dump(*a, **kw): Dump(*a, **kw)


class protocol_Logger:
  Debug: Callable[..., Any]
  Info : Callable[..., Any]
  Warn : Callable[..., Any]
  Error: Callable[..., Any]
  Dump : Callable[..., Any]


class mixin_Logger(protocol_Logger, _mixin):
  _logger: logging.Logger

  @classmethod
  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    cls._logger = _logger.getChild(cls.__name__)
    for name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)): setattr(cls, name, staticmethod(partial(fn, logger=cls._logger)))

  def __init__(self, *a, **kw):
    super(mixin_Logger, self).__init__(*a, **kw)
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(self, name, getattr(self.__class__, name))
# endregion


# region Foundation
class _Logger(mixin_Logger): pass


class _Config(mixin_Config):
  _base_path: Path

  def __init__(self, **kw) -> None:
    super().__init__(**kw)
    if Env.initialized:
      self._config_from_env()
    self._base_path = Path('.')

  # def my_path(self, path) -> Path: return self._base_path / self.my(path)


class _Base(_Logger, _Config): pass
# _App / App moved to gppu.app (App needs _DC, below; defined there to keep the
# App family together with the lifecycle/AsyncApp).
# endregion


# region DC - pseudo DataClass
_DC_BASE_TYPE_MAP = {'str': str, 'list': list, 'dict': dict, 'set': set, 'int': int, 'float': float, 'bool': bool, 'None': type(None)}
# Custom types register themselves here (e.g. iot.py adds y2eid/y2topic)


class _DC(UserDict):
  _DC_TYPE_MAP: dict[str, type] = _DC_BASE_TYPE_MAP.copy()
  _DC_EXCLUDE_NAMES: list[str] = []


  def _init_from_kw(self, **kw) -> None:
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data


  _INIT_STEPS: list[Callable] = [_init_from_kw]


  def __init_subclass__(cls, **kw) -> None:
    def _simple_type(typ: type | str) -> str:
      typ = str(typ)
      origin, bracket, _ = typ.partition('[')
      return origin if bracket and origin in cls._DC_TYPE_MAP else typ

    super().__init_subclass__(**kw)

    annotations_raw = [(n, t if type(t) == str else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_' and n not in cls._DC_EXCLUDE_NAMES]
    annotations = {n: _simple_type(t) for n, t in annotations_raw}

    mro = [(n, t) for n, t in annotations.items() if n[0] != '_' and t in cls._DC_TYPE_MAP]
    for aname, atype in mro:
      def getter(self, name=aname, atype=atype):
        result = self.data.get(name)
        if result is not None and isinstance(result, cls._DC_TYPE_MAP[atype]): return result
        if not result:
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  def __init__(self, **kw):
    self.data = {}
    for step in self._INIT_STEPS: step(self, **kw)

# endregion
