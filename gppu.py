from __future__ import annotations

import pprint
import yaml
import re
import inspect
import logging
import sys
import platform
import asyncio
import json

from pathlib import Path

from functools import wraps, partial

from typing import Union, Any, Literal, List, Optional, Tuple, Dict, DefaultDict
from typing import TypeAlias, ClassVar, Callable, Protocol

from string import Template

from collections import defaultdict, UserDict, UserList
from datetime import datetime
from enum import Enum


VER_GPPU_BASE = '2.26.0'
VER_GPPU_BUILD = '251122'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"


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
KEYS_FIRST = ['name', 'path']


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

    _ = [k for k in KEYS_FIRST if k in d]
    # ! Support for Null keys is not finished and its unclear if it is needed anymore
    ordered_keys = _ + sorted([str(k) if k else '?' for k in d.keys() if k not in KEYS_FIRST and k not in KEYS_DROP])
    for k in ordered_keys:
      if k == '?': v = d.get(None)
      else: v = d.get(k)
      
      if k in KEYS_DROP: continue
      elif k in KEYS_FORCE_STRING: _ = str(v)
      elif _isdict(v): _ = _sanitize_dict(v)
      elif _islist(v): _ = _sanitize_list(v)
      elif _isnumber(v): _ = v
      else: _ = str(v) if v else None
      result[str(k)] = _
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


def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
  return dumper.represent_dict(dict(enumerate(data)))


def dict_to_yml(filename:str, data=None, sort_keys=False):
  class IndentedListDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
      return super(IndentedListDumper, self).increase_indent(flow, False)

  assert filename
  if not data: return

  redata = dict_sanitize(data, sort_keys=sort_keys)

  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, _tuple_representer)
  with open(filename,'w+') as f:
    try: yaml.dump(redata, f, indent=2, Dumper=IndentedListDumper, sort_keys=False, width=2147483647)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
      with open(filename+'_error.txt','w+') as ferr: ferr.write(error)


def dict_from_yml(filename: str | Path):
  filename = str(filename)
  yml_root = filename.rsplit('/', 1)[0]

  def yml_include(loader, node):
    if node.value[0] == '/': filename = node.value
    else: filename = yml_root+'/'+node.value
    with open(filename, "r") as f: return yaml.load(f, Loader=yaml.FullLoader)

  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, _tuple_representer)
  yaml.add_constructor("!include", yml_include, Loader=yaml.FullLoader)

  with open(filename) as f: return dict(yaml.load(f, Loader=yaml.FullLoader))


def dict_template_populate(o, data: dict = {}, excludes:list = []) -> dict:
  """ 
    Returns new dictionary, copy of o with all templatable elements filled-in from data 
    
    This function is recursive

    Keys with value == 'DEL' are removed from result
    Keys with '$' in value are treated as templates and filled-in from data
  """
  _ = template_populate(o, data, excludes)
  return _ if isinstance(_, dict) else {}


def template_populate(o, data: dict = {}, excludes:list = []) -> Any:
  """ 
    Returns new object, copy of o with all templatable elements filled-in from data 
    
    This function is recursive

    Keys with value == 'DEL' are removed from result
    Keys with '$' in value are treated as templates and filled-in from data
  """
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


# region prettify and slugify
def pfy(object) -> str: return "\n"+pprint.pformat(object, indent=4, width=40, compact=True)
def slugify(o) -> str:
  """Converts any object to string, then slugifies it"""
  return re.sub(r'[^a-zA-Z0-9_]', '_', str(o).lower())
# endregion


# region Tracing decorators
_TracerAction: TypeAlias = Literal['before', 'after', 'instead']

TA_BEFORE: _TracerAction = 'before'
TA_AFTER: _TracerAction = 'after'
TA_INSTEAD: _TracerAction = 'instead'
TAs: list[_TracerAction] = [TA_BEFORE, TA_AFTER, TA_INSTEAD]


def _tracer(tracer: Optional[Callable[..., Any]] = None, action: Optional[_TracerAction] = None) -> Callable:
  def decorator(method: Callable) -> Callable:
    def wrapper(self, *a, **kw):
      if not tracer: return method(self, *a, **kw)
      if action == TA_BEFORE:
        tracer(self, *a, **kw)
        return method(self, *a, **kw)
      if action == TA_AFTER:
        _ = method(self, *a, **kw)
        tracer(self, *a, **kw)
        return _
      if action == TA_INSTEAD:
        return tracer(self, *a, **kw)
    return wrapper
  return decorator

# Thread-local storage to track profiling depth (shared across all profile_method decorators)
# import threading
# _profile_thread_locals = threading.local()

# def profile_method(func: Callable) -> Callable:
#   """Decorator to profile a method using cProfile.

#   Prints profiling stats sorted by cumulative time after method execution.
#   Handles nested calls by only profiling the outermost call.
#   """
#   import cProfile
#   import pstats
#   import io

#   @wraps(func)
#   def wrapper(*args, **kwargs):
#     # Check if we're already profiling in this thread
#     if not hasattr(_profile_thread_locals, 'profiling_depth'): _profile_thread_locals.profiling_depth = 0

#     is_outermost = _profile_thread_locals.profiling_depth == 0
#     _profile_thread_locals.profiling_depth += 1

#     if is_outermost: profiler = cProfile.Profile(); profiler.enable()

#     try: return func(*args, **kwargs)
#     finally:
#       _profile_thread_locals.profiling_depth -= 1

#       if is_outermost:
#         profiler.disable()

#         # Print stats to string buffer
#         s = io.StringIO()
#         stats = pstats.Stats(profiler, stream=s)
#         stats.strip_dirs()
#         stats.sort_stats('cumulative')
#         stats.print_stats(20)  # Print top 20 functions

#         # Get the class and method name
#         class_name = args[0].__class__.__name__ if args else 'unknown'
#         print(f"\n{'='*80}")
#         print(f"Profile for {class_name}.{func.__name__}")
#         print('='*80)
#         print(s.getvalue())

#   return wrapper
# endregion


# region Async helpers
def sync(func: Callable) -> Callable:
  """Wrapper to call async functions without await from synchronous code."""
  @wraps(func)
  def wrapper(*args, **kwargs):
    coro = func(*args, **kwargs)
    try:
      loop = asyncio.get_running_loop()
      return asyncio.create_task(coro)
    except RuntimeError:
      try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
          loop = asyncio.new_event_loop()
          asyncio.set_event_loop(loop)
      except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
  return wrapper
# endregion


# region y2xxx
# xx                                                                                        
# xx y2list, y2path and y2slug                                                              
# xx                                                                                        
""" y2list-based: y2path, y2slug"""
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
  def __init__(self, *args):
    data = []
    self.token = '/'

    for a in args: data += self._any2list(a)
    self.data = self._any2list(data)


class y2topic(y2path):
  def is_wildcard(self) -> bool: return bool(set(self.data) & {"#", "+"})


class y2slug(y2list):
  def __init__(self, o): 
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)


class y2eid:
  ns: str
  domain: str
  slug: y2slug 
  default_ns: ClassVar[str] = 'yala'
  default_domain: ClassVar[str] = 'entity'
  _ready: bool = False

  def __bool__(self) -> bool: return self._ready

  def __init__(self, o: Any, ns: Optional[str] = None, **kw):
    self._ready = False
    if not o: raise ValueError("y2eid: empty input")

    ns = ns or self.default_ns
     
    if isinstance(o, y2eid): s = str(o)
    elif isinstance(o, dict): s = str(o.get('entity_id',""))
    elif isinstance(o, str): s = o
    elif hasattr(o, 'entity_id') and hasattr(o, 'namespace'): s = f"{o.entity_id}@{o.namespace}"
    elif hasattr(o, 'entity_id') and hasattr(o, 'ns'): s = f"{o.entity_id}@{o.ns}"
    elif hasattr(o, 'seid'): s = o.seid
    else: raise ValueError

    self.ns = ns
    if '.' in s: self.domain, s = s.split('.',1)
    if '@' in s: s, self.ns = s.rsplit('@',1)
    self.ns = self.ns or self.default_ns
    self.domain = self.domain or self.default_domain
    self.slug = y2slug(s)

    for k in ['tail', 'head']: setattr(self, k, getattr(self.slug, k))
    self._ready = True


  def __str__(self):
    s = str(self.slug)
    if self.domain: s = self.domain + '.' + s
    if self.ns: s += '@' + self.ns
    return s
  def __repr__(self): return str(self)
  def __hash__(self): return hash(str(self))
  def __eq__(self,other): return str(self) == str(other)
  def __lt__(self,other): return str(self) < str(other)


  def endswith(self, ix) -> bool: return self.slug.endswith(ix)
  def startswith(self, ix) -> bool: return self.slug.endswith(ix)
  @property
  def entity_id(self) -> str: return f"{self.domain}.{self.slug}" if self._ready else ""
  @property
  def seid(self): return str(self)
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
  Pretty colored print. Supports two kinds of input:
    level, msg: compatible with default logger
    [args]: used by self.Dargs to colorize output
  Returns: colored string
  
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
_IGNORE_FUNCTIONS = ['dpcp', 'trace', 'pcp', 'Trace', 'Info', 'Debug', 'Warn', 'Error', '_LogColorizer']
_SEVERITY_COLORS = {'Error': 'WRED', 'Warn': 'WYELLOW', 'Info': 'WBLUE', 'Debug': 'GRAY4', None: 'WPURPLE'}
def dpcp(*a: Any, 
         conditional: Optional[bool] = None, 
         rules: Dict[str, bool] = {}, 
         no_prefix: bool = False, 
         severity: Optional[str] = None,
         **kw: Any) -> str | None:
  """ Version of pcp that adds info on where it was called from """
  def is_traced(name : Optional[str] = None) -> bool:
    if not conditional: return True
    if not name or name not in rules: return rules.get('all', False)
    else: return rules.get(name, False)

  def is_ignored(f, fi) -> bool:
    if 'python' in fi.filename: return True # !!! Ignoring all python3 libraries
    elif fi.function in _IGNORE_FUNCTIONS: return True
    elif f.f_locals.get('self').__class__.__name__ in _IGNORE_FUNCTIONS: return True
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
  # Print a string in a given color, right-justified or left-justified
  # to a given length.  The color is optional.
  #
  # Inputs:
  #   text: The text to print
  #   color: The color to print it in, defaulting to no color
  #   format: The format string, which is a number followed by a
  #           left or right justification character.  If no number
  #           is given, the number is assumed to be 0.
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


class PrettyColoredFormatter(logging.Formatter):
  def format(self, record):
    """
    Override the default formatter to provide pretty and colored output.
    """
    # Extract custom attributes if present
    verbose = getattr(record, 'verbose', False)
    level = record.levelname
    msg = super().format(record)  # Default formatting for the message

    # Apply colorization
    out = _colorize_log(msg=msg, level=level)
    if hasattr(record, 'args') and record.args:
      args = list(record.args) if not isinstance(record.args, list) else record.args
      out += _colorize_list(args) # type: ignore

    kwargs = getattr(record, 'kwargs', None)
    if verbose and isinstance(kwargs, dict): out += pfy(kwargs)

    return out


class PrettyColoredHandler(logging.StreamHandler):
  def emit(self, record):
    silent = getattr(record, 'silent', False)
    if not silent: super().emit(record)


def _fmt(*a, severity: str = 'Debug', **kw) -> str:
  if severity.upper() == 'DEBUG': result = dpcp(*a, rules=TRACE_RULES or {}, conditional=True, **kw)
  else: result = dpcp(*a, conditional=False, severity=severity, **kw)
  return result if result else ''


class _LogColorizer(logging.Formatter):
  def format(self, record: logging.LogRecord) -> str:
    args = [record.msg]
    if record.args is not None: 
      args.extend(record.args)
    result = _fmt(*args, severity=record.levelname)
    return result
# endregion


# @@      mixin class                                                           == 
class _mixin: pass

# region Logger
# ^~            Logger                                            
TRACE_RULES: dict = {}

_logger = logging.getLogger('gppu')
_logger.setLevel(logging.DEBUG)  # Ensure logger level is set to DEBUG


class _EmptyMessageFilter(logging.Filter):
  """Filter that removes records that would produce empty output"""
  def filter(self, record: logging.LogRecord) -> bool:
    # We need to temporarily format to check if output would be empty
    formatter = _LogColorizer()
    result = formatter.format(record)
    # Strip whitespace and ANSI color codes to check if truly empty
    # Remove all ANSI escape sequences
    import re
    cleaned = re.sub(r'\x1b\[[0-9;]*m', '', result)
    # Only log if we have actual content after stripping ANSI codes and whitespace
    return bool(cleaned.strip())


_sh = logging.StreamHandler()
_sh.setLevel(logging.DEBUG)
_sh.setFormatter(_LogColorizer())
_sh.addFilter(_EmptyMessageFilter())
_logger.addHandler(_sh)


def init_logger(name: str = 'gppu', trace_rules: dict | None = None) -> None:
  """Initialize global logger with a specific name and optional trace rules."""
  global _logger, TRACE_RULES
  if trace_rules is not None: TRACE_RULES = trace_rules
  Logger.trace_rules = TRACE_RULES
  new_logger = logging.getLogger(name)
  new_logger.setLevel(logging.DEBUG)
  new_logger.handlers = []
  new_logger.addHandler(_sh)
  _logger = new_logger
  for cls in list(mixin_Logger.__subclasses__()):
    cls._logger = _logger.getChild(cls.__name__)
    for n, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)): setattr(cls, n, staticmethod(partial(fn, logger=cls._logger)))


def Debug(*a, logger=None, **kw): (logger or _logger).debug(*a, **kw)
def Info(*a, logger=None, **kw): (logger or _logger).info(*a, **kw)
def Warn(*a, logger=None, **kw): (logger or _logger).warning(*a, **kw)
def Error(*a, logger=None, **kw): (logger or _logger).error(*a, **kw)
@sync
async def Dump(filename: str, data={}, **kw) -> None:
  """ Saves data object to yml file in trace folder """
  if '.' not in filename or not filename.endswith('.yml'): filename += '.yml'
  if Logger.trace_folder:
    filename = f"{Logger.trace_folder}/{filename}"
  dict_to_yml(filename=filename, data=data)


class Logger:
  """Namespace wrapper exposing logging helpers."""
  trace_folder: str = ''
  trace_rules: dict = TRACE_RULES

  @staticmethod
  def Debug(*a, **kw): Debug(*a, **kw)
  @staticmethod
  def Info(*a, **kw): Info(*a, **kw)
  @staticmethod
  def Warn(*a, **kw): Warn(*a, **kw)
  @staticmethod
  def Error(*a, **kw): Error(*a, **kw)
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
    # instance shortcuts re-use the class-level bound functions
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(self, name, getattr(self.__class__, name))
# endregion


# region Environment
class BaseDirType(Enum):
  CODE = "code"
  CONFIG = "config"
  DATA = "data"

class PathBuilder:
  """
  sudo mkdir /mnt/SD

  sudo mount.cifs //s1.karel.in/SD /mnt/SD -o username=alex,password=%%
  echo "//s1.karel.in/SD /mnt/SD cifs username=alex,password=%%,iocharset=utf8,vers=3.0 0 0" | sudo tee -a /etc/fstab

  """
  _CODE_BASE_PATHS = {
    OSType.W11: Template("D:\\Dev"),
    OSType.WSL: Template("/home/$user"),
    OSType.LINUX: Template("/home/$user"),
    OSType.MACOS: Template("/Users/$user"),
  }
  _SHARED_DATA_PATHS = {
    OSType.W11: Template("D:\\SD"),
    OSType.WSL: Template("/mnt/d/SD"),
    OSType.LINUX: Template("/mnt/SD"),
    OSType.MACOS: Template("/Users/$user/SD"),
  }

  # _KEY_PATH = Path("RAN/Keys")
  user: str
  app_name: str
  app_path: Path

  _os: OSType
  _base_path: Path

  def config_file(self) -> Path:
    file = self.app_path / Path(self.app_name).with_suffix('.yaml')
    if not file.exists():
      file = self.app_path / 'config.yaml'
    if not file.exists():
      raise FileNotFoundError(f"Config file not found for app '{self.app_name}' in path '{self.app_path}'")
    return file

 
#   def shared_data_path(self, path: Path) -> Path: return self._shared_data_path / path


  def __init__(self, app_name: str, user: str = 'alex', app_path: Optional[Path] = None) -> None:
    self.user = user
    self.app_name = app_name

    self._os = detect_os()
    if self._os == OSType.W11: self._base_path = Path("D:\\Dev")
    elif self._os in [OSType.WSL, OSType.LINUX]: self._base_path = Path(f"/home/{self.user}")
    elif self._os == OSType.MACOS: self._base_path = Path(f"/Users/{self.user}")
    else: raise Exception(f"Unsupported OS: {self._os.value}")

    # if app_path is None: app_path = self._base_path
    # elif app_path.absolute(): self.app_path = Path(app_path)
    # else: self.app_path = self._base_path / Path(app_path)
    self.app_path = self._base_path 
    if app_path: self.app_path /= app_path

    # self._code_path = Path(self._CODE_BASE_PATHS[self._os].safe_substitute(user=self.user))
    # self._shared_data_path = Path(self._SHARED_DATA_PATHS[self._os].safe_substitute(user=self.user))


class Env:
  name: str
  data: dict[str, Any] = {}
  initialized: bool = False

  _path_builder: PathBuilder
  _logger: logging.Logger

  def __init__(self, name: str, app_path: Path):
    import __main__
    Env.name = name or __main__.__file__
    Env._path_builder = PathBuilder(user='alex', app_name=Env.name, app_path=app_path)

    Env._logger = _logger.getChild(Env.name)
    for name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)): 
      setattr(Env, name, staticmethod(partial(fn, logger=Env._logger)))


  @staticmethod
  def load() -> None:
    config_file = Env._path_builder.config_file()
    config_data = dict_from_yml(config_file)
    Env._from_dict(config_data)


  @staticmethod
  def _from_dict(d: dict) -> None:   # * Loader
    if Env.initialized or Env.data: Env._reset(); Logger.Info('INFO', 'Environment', 'WRED', 'reset()')
    
    # sdp = str(Env._path_builder._shared_data_path)
    # extra = {"code_path": str(Env._path_builder._code_path), 
    #          "shared_data_path": sdp,
    #          "shared_data": sdp}
    s = json.dumps(d)
    extra = {}
    Env.data = json.loads(Template(s).safe_substitute(**extra))
    Env.initialized = True

  @staticmethod
  def _reset() -> None: Env.data = {}; Env.initialized = False

  @staticmethod
  def glob(path, default=None) -> Any: return deepget(path, Env.data, default=default)
  @staticmethod
  def glob_int(path, default: int = 0) -> int: return deepget_int(path, Env.data, default=default)
  @staticmethod
  def glob_list(path, default=[]) -> list: return deepget_list(path, Env.data, default=default)
  @staticmethod
  def glob_dict(path, default={}) -> dict: return deepget_dict(path, Env.data, default=default)
  @staticmethod
  @sync
  async def dump():
    Logger.Dump('Env.data', Env.data)
    return await asyncio.sleep(0)  # Make it truly async


class mixin_Config(_mixin):
  _my: dict[str, Any] = {}

  def _config_from_key(self, key: str) -> None:  self._my.update(Env.glob_dict(key))
  def _config_copy(self, other: mixin_Config) -> None: self._my = dict(other._my)

  def my(self, path, default=None) -> Any: return deepget(path, self._my, default=default)
  def my_int(self, path, default: int = 0) -> int: return deepget_int(path, self._my, default=default)
  def my_float(self, path, default: float = float('nan')) -> float: return deepget_float(path, self._my, default=default)
  def my_list(self, path, default: list = []) -> list: return deepget_list(path, self._my, default=default or [])
  def my_dict(self, path, default: dict = {}) -> dict: return deepget_dict(path, self._my, default=default or {})
# endregion


# ==                              DC - DataClass                              ==                                           
# region DC - pseudo DataClass
_DC_BASE_TYPE_MAP = {'str': str, 'list': list, 'dict': dict, 'set': set, 'int': int, 'float': float, 'bool': bool, 'None': type(None), 'y2eid': y2eid}


class DC(UserDict):
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
      if typ.startswith('list['): return 'list'
      return typ

    super().__init_subclass__(**kw)

    annotations_raw = [(n, t if type(t) == str else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_' and n not in cls._DC_EXCLUDE_NAMES]
    annotations = {n: _simple_type(t) for n, t in annotations_raw}
    
    mro = [(n, t) for n, t in annotations.items() if n[0] != '_' and t in cls._DC_TYPE_MAP]
    # print(f"DC.__init_subclass__: {cls.__name__} with fields: {[m[0] for m in mro]}\n")
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


# region Foundation
Config = Env

glob = Config.glob
glob_int = Config.glob_int
glob_list = Config.glob_list
glob_dict = Config.glob_dict

class _Logger(mixin_Logger): pass

class _Config(mixin_Config):
  _base_path: Path

  def __init__(self, **kw) -> None:
    super().__init__()
    assert Config.initialized, "Env must be initialized before using ContactImporter"
    key = kw.get('config_key', None)

    if key:
      self._config_from_key(key)
      self._base_path = Path(self.my('base_dir'))
    else:
      self._base_path = Path('.')

  def my_path(self, path) -> Path: return self._base_path / self.my(path)


class _Base(_Logger, _Config): pass
# endregion