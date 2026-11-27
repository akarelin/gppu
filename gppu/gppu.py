from __future__ import annotations

import pprint

import re
import os
import pathlib

import logging
import sys
import platform
import asyncio
import contextvars
import inspect
import builtins
import json
import getpass
import socket

from string import Template
from copy import copy, deepcopy
from pathlib import PurePath, PureWindowsPath

from enum import Enum
from abc import abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Union, Any, List, Optional, Tuple, Dict, DefaultDict, Callable, Concatenate, Self, final, Coroutine
from collections import defaultdict, UserDict, UserList
from collections.abc import Mapping

from functools import cache, partial, wraps
from datetime import datetime as dt, timedelta
from zoneinfo import ZoneInfo

import yaml
from yaml.dumper import Dumper
from yaml.representer import SafeRepresenter
from yaml.loader import FullLoader
from yaml.nodes import Node
from jinja2 import DictLoader, StrictUndefined, Undefined, meta, pass_context
from jinja2.nativetypes import NativeEnvironment
from jinja2.sandbox import SandboxedEnvironment


from importlib.metadata import version

VER_GPPU = version("gppu")

MY_TZ = ZoneInfo("America/Los_Angeles")

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
  elif sysname == "Darwin": return OSType.MACOS
  elif sysname == "Linux":
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release or 'WSL_DISTRO_NAME' in os.environ: return OSType.WSL
    return OSType.LINUX
  else: return OSType.OTHER


def full_path(path: str | Path, base_dir: str | Path | None = None, *, strict: bool = False) -> Path:
  """gppu.fs's and the Lake's, out of scope for now: the path against base_dir or the current folder, resolved."""
  result = Path(path)   # .. Path expands a text path's variables, its ~ and a WSL drive; an absolute path stays as it is
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
  try: then = dt.fromisoformat(str(o)).timestamp()
  except: then = 0.0
  return now_ts() - then
def _safe_datetime(o: object) -> dt | None:
  if isinstance(o, int | float): 
    try: result = dt.fromtimestamp(o, MY_TZ)
    except (OverflowError, OSError, ValueError): return None
    return result
  
  if isinstance(o, dt):
    if o.tzinfo is None: return o.replace(tzinfo=MY_TZ)
    return o.astimezone(MY_TZ)

  if isinstance(o, str):
    try: result = dt.fromisoformat(o)
    except: return None
    if result.tzinfo is None: return result.replace(tzinfo=MY_TZ)
    return result.astimezone(MY_TZ)
# endregion


# region Time helpers
def now_str(): return dt.now().strftime("%Y%m%d.%H%M%S")
def now_ts(): return dt.now().timestamp()

def timestamp(): return dt.now().strftime("%y%m%d-%H%M")
def datestamp(): return dt.now().strftime("%y%m%d")


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
# endregion



# region special formatters
def pfy(o) -> str: return "\n"+pprint.pformat(o, indent=4, width=40, compact=True)
def slugify(o) -> str:
  """Converts any object to string, then slugifies it"""
  return re.sub(r'[^a-zA-Z0-9_]', '_', str(o).lower())

# endregion


# region Native Types
class Span:
  @abstractmethod
  def __contains__(self, value: Span) -> bool: ...


class TimeSpan(Span):
  """[start, end], its end None while it goes on; a date and a duration, [date, date + duration]; a date alone,
  [date, date + 1 day); a ts alone, [ts, ts + 1 second). A duration is a timedelta or seconds. `bounds` says
  which ends it holds: '[]' both, '[)' not its end."""
  start: dt
  end: dt | None
  bounds: str

  def __init__(self, start=None, end=None, *, date=None, duration=None, ts=None, bounds: str = '[]'):
    length = None
    if ts is not None: start, length, bounds = ts, timedelta(seconds=1), '[)'
    elif date is not None and duration is not None: start, length = date, duration if isinstance(duration, timedelta) else timedelta(seconds=duration)
    elif date is not None: start, length, bounds = date, timedelta(days=1), '[)'
    self.start = _safe_datetime(start)
    if self.start is None: raise ValueError('TimeSpan requires a valid start')
    self.end = self.start + length if length is not None else None if end is None else _safe_datetime(end)
    if end is not None and self.end is None: raise ValueError('TimeSpan requires a valid end or none')
    if self.end is not None and self.end < self.start: raise ValueError('TimeSpan end precedes start')
    if bounds not in ('[]', '[)'): raise ValueError(f"TimeSpan bounds are '[]' or '[)', not {bounds!r}")
    self.bounds = bounds


class y2list(UserList):
  data: List[Any]
  token: str

  def _any2list(self, o) -> list:
    result = []
    if o:
      if hasattr(o, 'data'): o = o.data
      if isinstance(o, (list, tuple)): result = [_ for _ in o if _]
      elif self.token: result = str(o).split(self.token)
      else: result = re.findall('[a-zA-Z0-9]+', str(o))
    return result

  def __init__(self, o: Optional[Any] = None) -> None:
    super().__init__()
    self.token = ""
    self.data = self._any2list(o)


  def __str__(self): return self.token.join(self.data)
  def __repr__(self): return self.token.join(self.data)
  def __eq__(self, other: Any) -> bool:
    if hasattr(other, 'data'): return self.data == other.data
    else: return str(self) == str(other)
  def __hash__(self): return hash(str(self))  # type: ignore


  def upper(self): return str(self).upper()
  def lower(self): return str(self).lower()
  def encode(self, encoding='utf-8', errors='strict'): return str(self.data).encode(encoding, errors)
  def iadd(self, o): self.data += self._any2list(o)
  def to_json(self): return str(self)


  @property
  def head(self) -> Optional[str]: return self.data[0] if len(self.data) > 0 else None
  @property
  def tail(self) -> Optional[str]: return self.data[-1] if len(self.data) > 0 else None


  def endswith(self, ix) -> bool:
    slow = str(self).lower()
    if isinstance(ix, list):
      for element in ix:
        if slow.endswith(element.lower()): return True
      return False
    if '_' in ix: six = ix.replace('_',self.token)
    elif '/' in ix: six = ix.replace('/',self.token)
    else: six = ix.lower()
    return slow.endswith(six)
  def startswith(self, ix) -> bool:
    slow = str(self).lower()
    if isinstance(ix, list):
      for element in ix:
        if slow.startswith(element.lower()): return True
      return False
    if '_' in ix: six = ix.replace('_', self.token)
    elif '/' in ix: six = ix.replace('/', self.token)
    else: six = ix.lower()
    return slow.startswith(six)


  def extract(self, s:str, default=None):
    """
    Removes element by value and returns it or default
    ! modifies self.data
    """
    if s in self.data: return self.data.pop(self.data.index(s))
    return default


  def discard(self, element): self.data = [e for e in self.data if not e == element]
  def pophead(self) -> Optional[str]: return self.data.pop(0) if len(self.data) > 0 else None
  def poptail(self) -> Optional[str]: return self.data.pop(-1) if len(self.data) > 0 else None
  def popsuffix(self, ix):
    if self.endswith(ix):
      if '_' in ix and self.token != '_': ix = ix.replace('_',self.token)
      elif '/' in ix and self.token != '/': ix = ix.replace('/',self.token)
      self.data = self._any2list(str(self).replace(ix, ''))
      return self.token.join(self._any2list(ix))
  def popprefix(self, ix):
    if self.startswith(ix):
      if '_' in ix and self.token != '_': ix = ix.replace('_', self.token)
      elif '/' in ix and self.token != '/': ix = ix.replace('/', self.token)
      self.data = self._any2list(str(self).replace(ix, ''))
      return self.token.join(self._any2list(ix))
  def popxfix(self, ix): return self.popsuffix(ix) or self.popprefix(ix)


class y2path(y2list):
  """
    A slash-separated path held as a list. An element of the list can be called a segment,
    as in https://www.rfc-editor.org/rfc/rfc3986.html#section-3.3
  """
  def __init__(self, *args):
    data = []
    self.token = '/'
    self._lead = ''
    self._drive_root = False

    for i, a in enumerate(args):
      if isinstance(a, y2path): a = str(a)
      elif isinstance(a, os.PathLike): a = os.fspath(a)
      if isinstance(a, str):
        if os.sep != '/': a = a.replace(os.sep, '/')
        if i == 0:
          self._lead = '//' if a.startswith('//') else '/' if a.startswith('/') else ''
          self._drive_root = bool(PureWindowsPath(a).drive and PureWindowsPath(a).root)
      data += self._any2list(a)
    self.data = self._any2list(data)

  def __str__(self):
    result = self._lead + super().__str__()
    if self._drive_root and len(self.data) == 1 and result.endswith(':'): result += '/'
    return result

  def __truediv__(self, other: str | y2path) -> y2path:
    return y2path(self, other)


class y2topic(y2path):
  def is_wildcard(self) -> bool: return bool(set(self.data) & {"#", "+"})


class Path(y2path, pathlib.Path):
  """A file system path: y2path's segments and operators, everything else from pathlib.Path."""
  # _drv, _root, _tail_cached, _str, _parts_normcase_cached, _hash, _info = (_cached() for _ in range(7))
  _raw_paths = property(lambda self: [str(self)])
  _str_normcase = property(lambda self: pathlib.PurePath(self)._str_normcase)
  # .. pathlib keeps what it parsed; a Path's segments change, so it parses them each time and keeps nothing
  _drv = property(lambda self: pathlib.PurePath(self).drive, lambda self, value: None)
  _root = property(lambda self: pathlib.PurePath(self).root, lambda self, value: None)
  _tail_cached = property(lambda self: pathlib.PurePath(self)._tail, lambda self, value: None)

  def __init__(self, *args):
    # .. a path given as text is the user's: its variables, its leading ~, and on Windows a WSL drive (/mnt/d/x) are expanded, the two things pathlib does not do
    if args and isinstance(args[0], (str, os.PathLike)) and not isinstance(args[0], y2path):
      raw = os.path.expandvars(os.fspath(args[0]))
      if detect_os() == OSType.W11 and re.match(r'/mnt/([a-zA-Z])(?:/|$)', raw): raw = f'{raw[5].upper()}:/{raw[7:]}'
      args = (os.path.expanduser(raw) if raw == '~' or raw.startswith(('~/', '~\\')) else raw, *args[1:])
    y2path.__init__(self, *args)

  def __truediv__(self, other: str | y2path) -> Path: return Path(self, other)

  def open(self, mode: str = 'r', buffering: int = -1, encoding: str | None = None, *args, **kwargs):
    # .. text is UTF-8 unless a caller names another encoding (pathlib's read_text and write_text pass 'locale', Windows'
    # .. code page before Python 3.15)
    if 'b' not in mode and encoding in (None, 'locale'): encoding = 'utf-8'
    return pathlib.Path.open(self, mode, buffering, encoding, *args, **kwargs)

  def __eq__(self, other): return str(self) == str(Path(other)) if isinstance(other, PurePath) else y2path.__eq__(self, other)
  __hash__ = y2path.__hash__

  def copy(self, *args, **kwargs): return y2path.copy(self) if not args and not kwargs else pathlib.Path.copy(self, *args, **kwargs)


class y2uri:
  """
    Implements:
      https://www.rfc-editor.org/info/rfc3986/
      https://www.w3.org/TR/media-frags/
      https://www.w3.org/TR/fragid-best-practices
      https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Query
      https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Fragment/Media_fragments
      https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Fragment/Text_fragments
  
  """
  scheme: str
  path: y2path

  _fragment: str | None
  _query: str | None


  def __init__(self, o: Any, scheme: str | None = None):
    self._path_absolute = False
    self._last_segment_empty = False

    if isinstance(o, dict) and 'uri' in o: s = o['uri']
    else: s = str(o)

    if '://' in s:
      head, _, s = s.partition('://')
      if scheme and head and head != scheme: raise ValueError(f"Two schemas in uri {head} {scheme}")
      self.scheme = head or scheme or 'null'
    else: self.scheme = scheme or 'null'
    
    s, _, self._fragment = s.partition('#')
    s, _, self._query = s.partition('?')

    self.path = y2path(s.split('/'))
    self._path_absolute = s.startswith('/')
    self._last_segment_empty = s.endswith('/') and bool(self.path)

  def __str__(self) -> str:
    result = f'{self.scheme}://'
    if self._path_absolute: result += '/'
    result += str(self.path)
    if self._last_segment_empty: result += '/'
    if self._query: result += f'?{self._query}'
    if self._fragment: result += f'#{self._fragment}'
    return result

  def __repr__(self) -> str: return str(self)
  def __hash__(self) -> int: return hash(str(self))
  def __eq__(self, other): return str(self) == str(other)
  def to_json(self) -> str: return str(self)

  def __truediv__(self, path: y2path | str) -> 'y2uri':
    result = copy(self)
    result.path = self.path / path
    return result

  @property
  def query(self) -> str | None: return self._query

  @query.setter
  def query(self, value: str) -> None: self._query = value

  @property
  def fragment(self) -> str | None: return self._fragment
  
  @fragment.setter
  def fragment(self, value: str) -> None: self._fragment = value
  # region - Fragments
    # elif ':~:' in value:
    #   anchor, _, directives = value.partition(':~:')
    #   fields = {}
    #   if anchor: fields['anchor'] = unquote(anchor)
    #   fields['text'] = []
    #   for directive in directives.split('&'):
    #     name, separator, selector = directive.partition('=')
    #     if name != 'text' or not separator:
    #       raise ValueError('Unsupported text fragment directive')
    #     parts, text = selector.split(','), {}
    #     if parts[0].endswith('-'): text['prefix'] = unquote(parts.pop(0)[:-1])
    #     if parts and parts[-1].startswith('-'): text['suffix'] = unquote(parts.pop()[1:])
    #     if not 1 <= len(parts) <= 2 or not all(parts):
    #       raise ValueError('Text fragment requires textStart and optional textEnd')
    #     text['textStart'] = unquote(parts[0])
    #     if len(parts) == 2: text['textEnd'] = unquote(parts[1])
    #     fields['text'].append(text)
    #   self._fragment = fields
    # elif '=' in value:
    #   self._fragment = {key: values[0] if len(values) == 1 else values
    #     for key, values in parse_qs(value.replace('+', '%2B'), keep_blank_values=True).items()}
    # else:
      # self._fragment = {'anchor': unquote(value)} if value else {}
    # fields = self.fragment
    # if not fields: return ''
    # if set(fields) == {'anchor'}: return quote(fields['anchor'], safe='')
    # if 'text' not in fields:
    #   return urlencode(fields, doseq=True, quote_via=quote, safe=',:')
    # def escaped(value): return quote(value, safe='').replace('-', '%2D')
    # directives = []
    # for text in fields['text']:
    #   parts = []
    #   if 'prefix' in text: parts.append(escaped(text['prefix']) + '-')
    #   parts.append(escaped(text['textStart']))
    #   if 'textEnd' in text: parts.append(escaped(text['textEnd']))
    #   if 'suffix' in text: parts.append('-' + escaped(text['suffix']))
    #   directives.append('text=' + ','.join(parts))
    # anchor = quote(fields['anchor'], safe='') if 'anchor' in fields else ''
    # return anchor + ':~:' + '&'.join(directives)
  # endregion


# endregion


# region Dict utils: deepget, dict_all_paths
def deepget(path: str | y2path, d: dict, default=None):
  """The value at a slash path, falsy values included; default when any step is absent."""
  if path in d.keys(): return d[path]   # .. a key that holds a slash itself
  _ = d
  for pp in y2path(path):
    if not isinstance(_, Mapping) or pp not in _: return default
    _ = _[pp]
  return _


def deepget_int(path: str | y2path, d: dict, default: int = 0) -> int:
  """ Returns int at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, int) else default
def deepget_float(path: str | y2path, d: dict, default: float = float("NaN")) -> float:
  """ Returns float at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, float) else default
def deepget_list(path: str | y2path, d: dict, default: list = []) -> list:
  """ Returns list at path, or default if not found """
  return _ if isinstance(_ := deepget(path, d, default), list) else default
def deepget_dict(path: str | y2path, d: dict, default: dict = {}) -> dict:
  """ Returns dict at path, or default if not found """
  return _ if isinstance(_ := deepget(path, d, default), dict) else default


def deepset(path: str | y2path, d: dict, value) -> None:
  """The value written at a slash path, its missing parents made; a parent there that is not a mapping is refused
  before anything is written."""
  *parents, key = y2path(path)
  node = d
  for parent in parents:
    if parent not in node: break
    node = node[parent]
    if not isinstance(node, dict): raise TypeError(f'parent is not a mapping: {path}')
  node = d
  for parent in parents:
    if parent not in node: node[parent] = {}
    node = node[parent]
  node[key] = value
# endregion


# region working with yaml files: dict_to_yml, dict_from_yml, dict_sanitize
KEYS_FORCE_STRING = ['parent', '']
KEYS_DROP = ['api', 'context', 'hide_attributes']
KEYS_FIRST = ['name', 'seid', 'path']


def dict_sanitize(data: dict | list, sort_keys: bool = False) -> dict | list:
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

    if sort_keys: 
      key_sequence = [k for k in KEYS_FIRST if k in d]
      key_sequence += sorted((k for k in d.keys() if k not in KEYS_FIRST and k not in KEYS_DROP), key=lambda k: str(k) if k else '?')
    else:
      key_sequence = [k for k in d.keys()]

      
    for k in key_sequence:
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
    return bool({'y2list', 'str', 'y2topic', 'y2path'} & relatives)
  _islist = lambda o: not _isstring(o) and isinstance(o, (list, set))
  _isdict = lambda o: not _isstring(o) and (isinstance(o, (dict, defaultdict, UserDict)) or hasattr(o, 'as_dict') or (hasattr(o, 'data') and isinstance(o.data, dict)))
  _isnumber = lambda o: isinstance(o, (float, int))

  if _islist(data): return _sanitize_list(data)
  elif _isdict(data): return _sanitize_dict(data)
  else: raise ValueError(f"Unable to sanitize {data}")


def template_populate(o, data: dict = {}, excludes:list = []) -> Any:
  """ templates are simple inline functtions that return lists, dicts or scalars to be merged into dicts."""
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

  with Path(filename).open('w+') as f:
    try: yaml.dump(redata, f, indent=2, Dumper=IndentedListDumper, sort_keys=sort_keys, width=2147483647)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
      Path(f'{filename}_error.txt').write_text(error)


class YmlLoader(FullLoader):
  """dict_from_yml's loader; a module adds its tags here, as gppu.vault adds ``!secret``."""


def _tuple_representer(dumper: Dumper, data: tuple) -> Node:
  return dumper.represent_dict(dict(enumerate(data)))


def dict_from_yml(filename: str | Path) -> dict:
  """ yaml file to dictionary, resolving includes, but not templates"""
  filename = full_path(filename)
  dir_stack: list[Path] = [filename.parent]   # .. an include is relative to the folder of the file that holds it

  class Loader(YmlLoader): pass

  def yml_include(loader: FullLoader, node: Node) -> Any:
    fn = full_path(loader.construct_scalar(node), dir_stack[-1])
    dir_stack.append(fn.parent)
    try:
      with fn.open() as f:
        if fn.suffix.lower().endswith('.json'): return json.load(f)
        return yaml.load(f, Loader=Loader)
    finally: dir_stack.pop()

  Loader.add_constructor("!include", yml_include)

  with filename.open() as f: return dict(yaml.load(f, Loader=Loader))

# endregion


# region Jinja (AI, not human reviewed)
class JinjaEnvironment(SandboxedEnvironment, NativeEnvironment):
    """gppu's templates: Jinja with native values and gppu's formatting helpers, and the named templates a row's
    `template:` names. `jinja` is the one environment gppu renders with; loading a configuration adds its macros and
    named Jinja templates to it."""

    def __init__(self, **options):
        super().__init__(undefined=StrictUndefined, autoescape=False, **options)
        self.filters.update(self._jinja_helpers())
        self.globals.update(self._jinja_helpers())

    @staticmethod
    def _jinja_helpers() -> dict:
        """gppu's own filters, offered to every Jinja environment it builds."""
        return {
            'safe_int': safe_int, 'safe_float': safe_float, 'pfy': pfy, 'slugify': slugify,
        }

    @pass_context
    def _render_template_in(self, context, name: str, **values) -> Any:
        """A named template rendered from inside another one: it sees the caller's values, and its keywords win over them."""
        return self.get_template(name).render(context.get_all() | values)

    def render_template(self, template: str, values: Mapping = {}, /, **more) -> Any:
        """template, the name of a template in a `*_templates` block, a `$` template, or Jinja text, rendered with values and more."""
        values = {**values, **more}
        if template in self.loader.mapping: return self.get_template(template).render(values)
        if '{{' not in template and '{%' not in template and '$' in template:
            return Template(template).safe_substitute(values)
        return self._jinja_compile(template).render(values)

    def _jinja_configuration(self, node: Any) -> None:
        """Every named template (a `*_templates` block) of a configuration, wherever it sits, added to this environment."""
        if not isinstance(node, dict): return
        for key, value in node.items():
            if str(key).endswith('_templates') and isinstance(value, dict):
                self.loader.mapping.update(value)
                self.cache.clear()
            else: self._jinja_configuration(value)

    def _templates_of(self, node: Any, found: dict | None = None) -> dict:
        """Every template of a configuration by its name: a mapping in a `templates:` block. A name is declared once."""
        found = {} if found is None else found
        if isinstance(node, list):
            for value in node: self._templates_of(value, found)
        if not isinstance(node, dict): return found
        for key, value in node.items():
            if key == 'templates' and isinstance(value, dict):
                for name, template in value.items():
                    if not isinstance(template, dict): continue
                    if name in found: raise ValueError(f'template {name!r} is declared twice')
                    found[name] = template
            self._templates_of(value, found)
        return found

    def apply_template(self, node: Any, templates: dict) -> Any:
        """Every row of node whose `template:` names one of templates, merged over that template: the row wins. The
        template's Jinja that reads the row stays as written, for the app that renders it."""
        if isinstance(node, list): return [self.apply_template(value, templates) for value in node]
        if not isinstance(node, dict): return node
        node = {key: self.apply_template(value, templates) for key, value in node.items()}
        if isinstance(name := node.get('template'), str) and name in templates:
            return self.apply_template(templates[name], templates) | node
        return node

    def configuration(self, node: dict) -> dict:
        """A configuration as loaded: its named templates registered and its `template:` rows merged over their
        templates. Env's configuration and an app's own both load through it without evaluating Jinja."""
        self._jinja_configuration(node)
        return self.apply_template(node, self._templates_of(node))

    @cache
    def _jinja_compile(self, template: str):
        return self.from_string(template)

    def jinja_template(self, template: Any, /, **data) -> Any:
        """Render Jinja strings, including keys and values of a configuration node; missing inputs raise."""
        if isinstance(template, dict):
            return {key: self.jinja_template(value, **data) for key, value in
                    ((self.jinja_template(key, **data), value) for key, value in template.items()) if key != ''}
        if isinstance(template, list): return [self.jinja_template(value, **data) for value in template]
        if not isinstance(template, str): return template
        if '{{' not in template and '{%' not in template and '{#' not in template: return template
        value = self._jinja_compile(template).render(**data)
        if isinstance(value, Undefined): return str(value)
        return value


jinja =JinjaEnvironment(loader=DictLoader({}))
jinja.globals.update({name: getattr(builtins, name) for name in
                      ('dict', 'list', 'int', 'float', 'str', 'bool', 'len', 'round', 'sorted', 'min', 'max', 'range')},
                     re=re, render_template=jinja._render_template_in)

# .. the template functions are globals: the one environment's methods
render_template = jinja.render_template
apply_template, jinja_template = jinja.apply_template, jinja.jinja_template
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
  if not out.endswith('\u001b[0m'): out = out + '\u001b[0m' # .. Check if color reset is already present
  return out


_remove_prefixes = lambda s, prefixes: next((s.removeprefix(prefix) for prefix in prefixes if s.startswith(prefix)), s)
_SHORTEN_BY_PREFIX = ['process_', '_cb_']
_SEVERITY_COLORS = {'Error': 'WRED', 'Warn': 'WYELLOW', 'Info': 'WBLUE', 'Debug': 'GRAY4', None: 'WPURPLE'}


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
    
  return ''.join(result)  # .. Reset color at the end


def _colorize(text: str, colorcode:str, fmt=None):
  """
    Print a string in a given color.
    fmt: accepts formatting syntax with < and > anchors
  """
  # ESC = '\u001b'
  ESC = '\033'  # .. ANSI escape code for terminal colors
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



class _LogColorizer(logging.Formatter):
  """A record as gppu's coloured line: severity, caller, then the arguments as they were given."""
  ANSI = re.compile(r'\x1b\[[0-9;]*m')
  no_prefix = False

  def format(self, record: logging.LogRecord) -> str:
    args = list(record.gppu_args) if hasattr(record, 'gppu_args') else [record.getMessage()]
    if not self.no_prefix:
      function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
      class_name = record.name.removeprefix('gppu.') if record.name.startswith('gppu.') else ''
      caller = f'{class_name}.{function}' if class_name else function
      severity = 'Warn' if record.levelno == logging.WARNING else record.levelname.title()
      args = [_SEVERITY_COLORS.get(severity, _SEVERITY_COLORS[None]), severity, 'GRAY1', caller, 'NONE'] + args
    text = pcp(*args)
    if record.exc_info: text += '\n' + logging.Formatter().formatException(record.exc_info)
    if record.stack_info: text += '\n' + record.stack_info
    return text


class _EmptyMessageFilter(logging.Filter):
  """Drops an empty record, and a Debug record the trace rules do not trace."""

  def filter(self, record: logging.LogRecord) -> bool:
    if record.levelno == logging.DEBUG:
      function = _remove_prefixes(record.funcName or '', _SHORTEN_BY_PREFIX)
      names = [function, record.module, f'{record.module}.{function}']
      if record.name.startswith('gppu.'): names += [class_name := record.name.removeprefix('gppu.'), f'{class_name}.{function}']
      if not all(Logger.trace_rules[name] if name in Logger.trace_rules else Logger.trace_rules.get('all', False) for name in names): return False
    return bool(record.getMessage().strip() or record.exc_info)
# endregion

class _mixin: pass

# region Logger
# ^~            Logger
class Logger:
  """The program's one log: the console from the moment gppu is imported, with colours, and the trace rules the
  environment's configuration sets. A class that has ``mixin_Logger`` logs under its own name."""
  trace_folder: str = '.'
  trace_rules: dict = {}

  _root = logging.getLogger('gppu')
  _console = logging.StreamHandler(sys.stderr)
  _console.setFormatter(_LogColorizer())
  _console.addFilter(_EmptyMessageFilter())
  _root.setLevel(logging.DEBUG)
  _root.addHandler(_console)


def _log(logger: logging.Logger, level: int, a: tuple, kw: dict) -> None:   # .. a record's message is plain text; its arguments colour the console
  logger.log(level, _LogColorizer.ANSI.sub('', pcp(*a)), extra={'gppu_args': a}, stacklevel=3, **kw)
def Debug(*a, logger=Logger._root, **kw): _log(logger, logging.DEBUG, a, kw)
def Info(*a, logger=Logger._root, **kw): _log(logger, logging.INFO, a, kw)
def Warn(*a, logger=Logger._root, **kw): _log(logger, logging.WARNING, a, kw)
def Error(*a, logger=Logger._root, **kw): _log(logger, logging.ERROR, a, kw)
@sync
async def Dump(filename: str, data: dict = {}, **kw) -> None:
  """ Saves data object to yml file in trace folder """
  if '.' not in filename or not filename.endswith('.yml'): filename += '.yml'
  dict_to_yml(filename=Path(Logger.trace_folder) / filename, data=data)


class mixin_Logger(_mixin):
  """A class that has it logs under its own name with ``self.Info(...)``."""
  Dump = staticmethod(Dump)

  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    logger = Logger._root.getChild(cls.__name__)
    for name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error)): setattr(cls, name, staticmethod(partial(fn, logger=logger)))


# endregion


# region YMRO lifecycle

# region YMRO lifecycle - Sync
class _YMRO:
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']

  @property
  def _trace_mro(self) -> bool:
    return getattr(self, 'args', {}).get('trace_mro', False)
    

  def print_ymro(self):
    Debug('BY', self.__class__.__qualname__)
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    step = 'init'
    for sibling in siblings:
      Debug('DG', f"  {sibling.__qualname__}")
      qname = f"{sibling.__qualname__}__{step}"
      if qname[0] != '_': qname = '_' + qname
      method = getattr(self, qname, None)
      if method:
        Debug('INFO', f"  {method.__qualname__}")
        initers = getattr(sibling, '_initers', [])
        for initer in initers: Debug('DIM', f"     {initer.__qualname__}")


  def _ymros(self):
    result = {}
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    for step in self.POSSIBLE_STEPS:
      result[step] = []
      for sibling in siblings:
        qname = f"{sibling.__qualname__}__{step}"
        if qname[0] != '_': qname = '_' + qname
        method = vars(sibling).get(qname)
        if method: result[step].append(method.__get__(self))
    return result
  def _ymro(self, method: str) -> list: return self._ymros().get(method, [])

  
  def _callall(self, method: str, *a, **kw) -> None:
    for m in self._ymro(method): m(*a, **kw)


  @final
  def init(self) -> None:
    if self.initialized: return
    self._callall('init')
    self.initialized = True
  @property
  def initialized(self) -> bool: return getattr(self, '_initialized', False)
  @initialized.setter
  def initialized(self, value: bool): self._initialized = value


  def load(self) -> None:
    if self.loaded: return
    assert self.initialized
    self._callall('load')
    self.loaded = True
  @property
  def loaded(self) -> bool: return getattr(self, '_loaded', False)
  @loaded.setter
  def loaded(self, value: bool): self._loaded = value


  def start(self) -> None:
    if self.started: return
    self._callall('start')
    self.started = True
  @property
  def started(self) -> bool: return getattr(self, '_started', False)
  @started.setter
  def started(self, value: bool): self._started = value


  def stop(self) -> None:
    if not (self.started or self.loaded): return
    self._stopped = True
    self._callall('stop')
    self.started = False
    self.loaded = False

  @property
  def stopped(self) -> bool: return getattr(self, '_stopped', False)


YInit = YLoad = YStart = _YMRO
# endregion


# region Async
class YAsync(_YMRO):
  _loop: asyncio.AbstractEventLoop | None = None
  _task_group: asyncio.TaskGroup | None = None
  _background_tasks: set[asyncio.Task]


  async def _acallall(self, method: str, *a, **kw) -> None:
    for m in self._ymro(method):
      result = m(*a, **kw)
      if inspect.isawaitable(result): await result


  def __init(self) -> None:
    self._loop: asyncio.AbstractEventLoop | None = None
    self._task_group: asyncio.TaskGroup | None = None
    self._background_tasks: set[asyncio.Task] = set()
    self._stopped: bool = False


  @final
  async def load(self) -> None:   # type: ignore[override]
    if self.loaded: return
    assert self.initialized
    self._stopped = False
    await self._acallall('load')
    for child in getattr(self, '_children', ()):
      if isinstance(child, YAsync): await child.load()
      elif isinstance(child, _YMRO): child.load()
    self.loaded = True


  @final
  async def start(self) -> None:  # type: ignore[override]
    if self.started: return
    await self._acallall('start')
    for child in getattr(self, '_children', ()):
      if isinstance(child, YAsync): await child.start()
      elif isinstance(child, _YMRO): child.start()
    self.started = True
  async def __start(self) -> None:
    self._loop = asyncio.get_running_loop()


  @final
  def stop(self) -> None:
    if not (self.started or self.loaded): return
    self._stopped = True
    for child in reversed(getattr(self, '_children', ())):
      if isinstance(child, _YMRO): child.stop()
    self._callall('stop')
    self._loop = None
    self.started = False
    self.loaded = False

  def __stop(self) -> None:
    if self._loop is None: return
    tasks = list(self._background_tasks)
    self._loop.call_soon_threadsafe(lambda: [t.cancel() for t in tasks])


  def _get_loop(self) -> asyncio.AbstractEventLoop:
    if self._loop is not None: return self._loop
    if 'Runtime' in globals() and Runtime._loop is not None: return Runtime._loop
    raise RuntimeError(f'{self!r} is not running')


  def _spawn[T](self, coro: Coroutine[Any, Any, T], /) -> asyncio.Task[T]:
    task = self._task_group.create_task(coro) if self._task_group is not None else self._get_loop().create_task(coro)
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task


  def schedule[T](self, coro: Coroutine[Any, Any, T], /) -> Future[T]:
    return asyncio.run_coroutine_threadsafe(coro, self._get_loop())
# endregion
# endregion


# region DC - pseudo DataClass
_DC_BASE_TYPE_MAP = {'str': str, 'list': list, 'dict': dict, 'set': set, 'int': int, 'float': float, 'bool': bool, 'None': type(None),
                      'y2path': y2path, 'Path': Path, 'y2topic': y2topic, 'y2uri': y2uri}


class _DC(UserDict):
  """Pseudo-dataclass base class backed by a UserDict.

  Dynamically generates properties for annotated class attributes based on
  `_DC_TYPE_MAP`, providing default values for missing or falsy values and
  enabling dictionary-backed state management.
  """
  _DC_TYPE_MAP: dict[str, type] = _DC_BASE_TYPE_MAP.copy()
  _DC_EXCLUDE_NAMES: list[str] = []


  def _init_from_kw(self, **kw) -> None:
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data


  def _init_ymro(self, **kw) -> None:
    if isinstance(self, _YMRO): self.init()


  _INIT_STEPS: list[Callable[Concatenate[Any, ...], None]] = [_init_from_kw, _init_ymro]


  def __init_subclass__(cls, **kw) -> None:
    def _simple_type(typ: type | str) -> str:
      typ = str(typ)
      origin, bracket, _ = typ.partition('[')
      return origin if bracket and origin in cls._DC_TYPE_MAP else typ

    super().__init_subclass__(**kw)

    annotations_raw = [(n, t if isinstance(t, str) else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_' and n not in cls._DC_EXCLUDE_NAMES]
    annotations = {n: _simple_type(t) for n, t in annotations_raw}

    mro = [(n, t) for n, t in annotations.items() if n[0] != '_' and t in cls._DC_TYPE_MAP]
    for aname, atype in mro:
      if aname not in cls.__dict__ and isinstance(getattr(cls, aname, None), property): continue
      existing = cls.__dict__.get(aname)
      default_val = None if isinstance(existing, property) else existing
      def getter(self, name=aname, atype=atype, default_val=default_val):
        result = self.data.get(name)
        if result is not None and isinstance(result, cls._DC_TYPE_MAP[atype]): return result
        if not result:
          if default_val is not None: return default_val
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  @final
  def __init__(self, **kw):
    self.data = {}
    for step in self._INIT_STEPS: step(self, **kw)
# endregion


# region Configuration mixins
class mixin_Config(_mixin):
  """An object's configuration, its data, read back with my."""
  def my(self, path: str | y2path) -> Any: return deepget(path, self.data)
  def my_int(self, path: str | y2path, default: int = 0) -> int: return deepget_int(path, self.data, default=default)
  def my_float(self, path, default: float = float('nan')) -> float: return deepget_float(path, self.data, default=default)


class _Base(mixin_Logger, mixin_Config): pass
# endregion


# region DataObject
class DataObject(YInit, _Base, _DC):
  """Passive data + config + logging + parent/children tree. No loop, no CLI."""
  name: str

  def __init(self) -> None:
    self._parent: DataObject | None = self.data.pop('parent', None)
    self._children: list[DataObject] = []
    if not self.name: self.name = type(self).__name__.lstrip('_').lower()
    if isinstance(self._parent, DataObject): self._parent._children.append(self)

  @property
  def parent(self) -> DataObject | None: return self._parent
  @parent.setter
  def parent(self, value: DataObject | None) -> None: self._parent = value

  @property
  def children(self) -> list[DataObject]: return self._children

  def child(self, name: str) -> DataObject | None:
    return next((c for c in self._children if c.name == name), None)

  def _from_dict(self, d: Mapping, *, override: bool = True) -> Self:
    config = dict(d)
    topology = config.pop('topology', None)
    tunables = config.pop('tunables', None)
    data = dict_from_yml(topology) if topology else {}
    if isinstance(tunables, dict): data.update(tunables)
    data.update(config)
    self.data = (self.data | deepcopy(data)) if override else (deepcopy(data) | self.data)
    self.data = jinja.configuration(self.data)
    return self

  def _from_file(self, path: str | Path, *, override: bool = True) -> Self:
    """Load config from a YAML file, applying Jinja."""
    return self._from_dict(dict_from_yml(path), override=override)

  def reset(self) -> None:
    self.data = {}
    self.initialized = False
    self.loaded = False
    self.started = False


_BaseObject = DataObject
# endregion


# region App
class App(YAsync, DataObject):
  """An app: named as its class unless made with a name. Its configuration is its section of the environment with
  explicit ``config`` or its script's MANIFEST over it; what it is made with goes over that, and the command line over all."""

  def __init(self) -> None:
    script = vars(sys.modules[type(self).__module__])   # .. a script assigns its own configuration to its MANIFEST global
    if 'config' in self.data:
      cfg = self.data['config']
      override = cfg if isinstance(cfg, Mapping) else dict_from_yml(cfg)
    elif 'MANIFEST' in script: override = yaml.load(script['MANIFEST'], Loader=YmlLoader) or {}
    else: override = {}
    self._from_dict(glob_dict(self.name) | dict(override), override=False)
    argv = sys.argv[1:]   # .. --key value sets a key, a slash path a nested one, to the value read as YAML; --flag sets it to True
    for i, arg in enumerate(argv):
      if arg.startswith('--') and len(arg) > 2:
        deepset(arg[2:], self.data, yaml.load(argv[i + 1], Loader=YmlLoader) if i + 1 < len(argv) and not argv[i + 1].startswith('--') else True)

  def _from_manifest(self):
    frame = inspect.currentframe().f_back
    data = yaml.safe_load(frame.f_globals["MANIFEST"])["manifest"]
    if data: self.data |= data

  async def run(self, *, forever: bool = True) -> None:
    """init, load and start on this loop; returns when stopped (or after start if forever=False)."""
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    owns_runtime = Runtime._loop is None
    try:
      self._loop = asyncio.get_running_loop()
      if owns_runtime: Runtime._loop = self._loop
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        for step in (self.init, self.load, self.start):
          if inspect.isawaitable(result := step()): await result
        if forever and not self.stopped: self._spawn(asyncio.Event().wait())
    finally:
      self._task_group = None
      self._loop = None
      if owns_runtime: Runtime._loop = None
      self._background_tasks.clear()

  def run_sync(self, *, forever: bool = False) -> None:
    """Run this app synchronously on asyncio (SelectorEventLoop on Windows)."""
    factory = asyncio.SelectorEventLoop if sys.platform == 'win32' else None
    asyncio.run(self.run(forever=forever), loop_factory=factory)
# endregion


# region Callbacks & Timers
def _callback_wrapper(callback: Callable[..., Any]) -> Callable[..., Any]:
  """The callback called with only the keywords it takes."""
  signature = inspect.signature(callback)

  def wrapped(*args: Any, **data: Any) -> Any:
    if not signature.parameters: return callback()
    if any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values()):
      return callback(*args, **data)
    allowed = {
      name for name, param in signature.parameters.items()
      if param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
    }
    return callback(*args, **{k: v for k, v in data.items() if k in allowed})

  return wrapped


class mixin_Timers(YStart):
  """``run_later`` and ``run_every`` on its async app's or Runtime's loop. ``timers`` holds every armed timer's row by
  its id (its callback's name, its kind, its interval and its next run), ``h_timeouts`` those armed under a key."""

  def __init(self) -> None:
    self.timers: dict[int, dict] = {}
    self.h_timeouts: dict[str, dict] = {}
    self._executor = ThreadPoolExecutor()   # .. its callbacks' own threads: on the loop's default pool they would wait for the very lookups their device calls need

  def __stop(self) -> None:
    self.cancel_timers()
    self._executor.shutdown(wait=False)
    self._executor = ThreadPoolExecutor()   # .. a second run gets its own; a pool starts no thread until it is used

  def run_later(self, callback: Callable[..., Any], *, delay: int | float, key: str | None = None, **data: Any) -> Future:
    """``callback`` once, ``delay`` seconds from now; armed again under ``key``, the one armed under it before is
    cancelled. Any thread arms it; its handle's ``cancel()`` cancels it."""
    return self.schedule(self._timer(callback, float(delay), None, key, data))

  def run_every(self, callback: Callable[..., Any], *, start: int | float, interval: int | float, **data: Any) -> Future:
    """``callback`` ``start`` seconds from now, and again ``interval`` seconds after each run of it ends."""
    return self.schedule(self._timer(callback, float(start), float(interval), None, data))

  async def _timer(self, callback: Callable[..., Any], delay: float, interval: float | None, key: str | None, data: dict) -> None:
    # .. its row is in `timers`, and under its key in `h_timeouts`, while it is armed; sync callbacks run off the loop
    row = {'name': getattr(callback, '__name__', ''), 'kind': 'once' if interval is None else 'interval', 'interval': interval,
           'next_run': now_ts() + delay, 'task': asyncio.current_task()}
    if key in self.h_timeouts: self.h_timeouts[key]['task'].cancel()
    self.timers[id(row)] = row
    if key is not None: self.h_timeouts[key] = row
    is_async = inspect.iscoroutinefunction(callback)
    wrapped = _callback_wrapper(callback)
    try:
      while True:
        await asyncio.sleep(max(0.0, row['next_run'] - now_ts()))
        if interval is None:   # .. a one-shot is spent as it fires: its key is free while its callback runs
          del self.timers[id(row)]
          if self.h_timeouts.get(key) is row: del self.h_timeouts[key]
        try:
          if is_async: await wrapped(**data)
          else: await asyncio.get_running_loop().run_in_executor(self._executor, partial(contextvars.copy_context().run, wrapped, **data))
        except Exception as error: self.Error('timer', row['name'], 'raised:', error)
        if interval is None: return
        row['next_run'] = now_ts() + interval
    finally:
      self.timers.pop(id(row), None)
      if self.h_timeouts.get(key) is row: del self.h_timeouts[key]

  def cancel_timers(self) -> None:
    """Every timer this app armed, cancelled, from any thread."""
    for row in list(self.timers.values()): row['task'].get_loop().call_soon_threadsafe(row['task'].cancel)
# endregion


# region - Env, State, Runtime
class _Env(DataObject):
  """The program's environment: a read-only system object, made once as gppu is imported and hidden from programs. Its
  init knows the machine it runs on and loads its environment's file, so a reset followed by init is a reload."""
  _ENV_PATHS = {"RAN": "RAN/_config/config.yaml", "IoT": "IoT/_Creekview/_creekview.yaml"}   # .. the two environments, each in its repository

  home: Path
  os: OSType
  host: str
  user: str
  environment: str

  def __init(self) -> None:
    self.os = detect_os()
    self.host, self.user = socket.gethostname().split('.')[0].lower(), getpass.getuser()
    self.home = Path('D:/Dev') if self.os == OSType.W11 else Path.home()
    if not self.environment:
      self.environment = 'IoT' if {'IoT', 'y2'} & set(Path(sys.argv[0]).resolve().parts) or not (self.home / self._ENV_PATHS['RAN']).exists() else 'RAN'
    config = self.home / self._ENV_PATHS[self.environment]
    if config.exists(): self._from_file(config, override=False)   # .. a host without its repository reads its environment from MQTT

  def _from_dict(self, d: Mapping, *, override: bool = True) -> Self:
    super()._from_dict(d, override=override)
    if 'trace_rules' in self.data: Logger.trace_rules = dict(self.data['trace_rules'])
    return self

  def reset(self) -> None:
    super().reset()
    Logger.trace_rules = {}
    self.init()


Env = _Env()


# .. the configuration's readers are globals over Env's data
def glob(path: str | y2path) -> Any: return deepget(path, Env.data)
def glob_int(path: str | y2path, default: int = 0) -> int: return deepget_int(path, Env.data, default=default)
def glob_list(path: str | y2path) -> list: return deepget_list(path, Env.data, default=[])
def glob_dict(path: str | y2path) -> dict: return deepget_dict(path, Env.data, default={})


class _State(DataObject):
  """Shared mutable runtime state + object registry (deduplicated by key), optionally backed by gppu.data.Cache."""

  def __init(self) -> None:
    self._objects: dict[str, Any] = {}
    self._store: Any = None

  @property
  def objects(self) -> dict[str, Any]: return self._objects

  def register(self, key: str, obj: Any) -> Any:
    if not key: raise ValueError(f'Cannot register {obj!r} with empty key')
    if key in self._objects: raise ValueError(f'Duplicate object registration: {key}')
    self._objects[key] = obj
    return obj

  def unregister(self, key: str) -> None:
    self._objects.pop(key, None)

  def get_object(self, key: str) -> Any:
    if key not in self._objects: raise KeyError(f'Unknown object: {key}')
    return self._objects[key]

  def bind(self, path: str | Path, *, backend: str = 'sqlite') -> Self:
    """Attach a gppu.data.Cache backend for transparent persistence."""
    from .data import Cache
    self._store = Cache(str(path), ttl=0, backend=backend)
    return self

  def set_state(self, key: str, value: Any) -> None:
    self.data[key] = value
    if self._store is not None: self._store.set(key, value, ttl=0)

  def get_state(self, key: str, default: Any = None) -> Any:
    if key in self.data: return self.data[key]
    if self._store is not None:
      val = self._store.get(key, default)
      if val is not None: self.data[key] = val
      return val
    return default

  def reset(self) -> None:
    super().reset()
    self._objects = {}
    if self._store is not None: self._store.close(); self._store = None


State = _State()


class _Runtime(mixin_Timers, YAsync, DataObject):
  """The process's single async runtime: one event loop, timers, process launching, parallel execution, and app runner."""

  def attach(self, loop: asyncio.AbstractEventLoop | None = None) -> asyncio.AbstractEventLoop:
    self._loop = loop or asyncio.get_running_loop()
    return self._loop

  async def call(self, target: str, method: str, *args: Any, **kwargs: Any) -> Any:
    """Find a registered object in State by key and invoke its method (sync or async)."""
    obj = State.get_object(target)
    result = getattr(obj, method)(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result

  async def run_app(self, app: _YMRO, *, forever: bool = False) -> None:
    self.attach()
    try:
      for step in (app.load, app.start):
        if inspect.isawaitable(r := step()): await r
      if forever and not app.stopped:
        try: await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError): pass
        finally:
          if inspect.isawaitable(r := app.stop()): await r
    finally:
      self.cancel_timers()
      self._loop = None

  run = run_app

  async def launch(self, command: list[str], line: Callable[[str], Any], cwd: str | Path, env: Mapping[str, str] | None = None) -> str | None:
    """Start a process and hand `line` each line of its output; the error, or None when it exits with 0."""
    try:
      process = await asyncio.create_subprocess_exec(
        *command, cwd=str(cwd), env=dict(env) if env is not None else None,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
      )
      assert process.stdout is not None
      async for raw in process.stdout:
        line(raw.decode('utf-8', errors='replace').rstrip())
      if code := await process.wait():
        return f'process exited with {code}'
    except OSError as failure:
      return str(failure)
    return None

  async def run_parallel(
    self,
    units: list[Any],
    run: Callable[[Any], Coroutine[Any, Any, Any]] | None = None,
    conflicts: Callable[[Any, list[Any]], bool] | None = None,
    failed: Callable[[Any, BaseException], Any] | None = None,
  ) -> list[Any] | None:
    """Run coroutines (when ``run`` is None) or scheduled units in parallel, respecting optional ``conflicts`` and ``failed``."""
    if run is None:
      return list(await asyncio.gather(*units))
    pending, running = list(units), {}
    while pending or running:
      for unit in pending[:]:
        if conflicts is not None and conflicts(unit, list(running.values())): continue
        running[asyncio.create_task(run(unit))] = unit
        pending.remove(unit)
      finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
      for task in finished:
        unit = running.pop(task)
        if (exc := task.exception()) is not None:
          if failed is not None: failed(unit, exc)
          else: raise exc
    return None


Runtime = _Runtime()
# endregion
