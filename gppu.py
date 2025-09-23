import pprint
import yaml
import re
import inspect
import logging
import builtins
import sys
import platform

from pathlib import Path

# Rich library imports
from rich import print as rich_print
from rich.console import Console
from rich.logging import RichHandler
from rich.pretty import Pretty, pprint as rich_pprint
from rich.table import Table
from rich.text import Text
from rich.traceback import install as install_rich_traceback
from rich.theme import Theme

from abc import abstractmethod
from functools import wraps, partial
from pydoc import locate

from types import ModuleType, UnionType, FrameType

from typing import Union, Callable, Any, Literal, List, Optional, Tuple, Dict, DefaultDict
from typing import Type, TypeVar, TypeAlias, ClassVar
from typing import ForwardRef, ParamSpec, Protocol, get_type_hints
from typing import get_origin, get_args, final, cast

from string import Template

from collections import defaultdict, UserDict, UserList
from datetime import datetime


VER_GPPU_BASE = '2.20.0'
VER_GPPU_BUILD = '250824-rich'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

# Initialize Rich console with custom theme
custom_theme = Theme({
    "error": "bold red",
    "warning": "bold yellow",
    "info": "bold blue",
    "debug": "dim white",
    "success": "bold green",
    "trace": "dim cyan",
    "critical": "bold white on red",
    "highlight": "bold magenta",
})

# Create a global console instance
console = Console(theme=custom_theme, force_terminal=True)

# Install rich traceback handler for better error display
install_rich_traceback(console=console, show_locals=True)


_T = TypeVar('_T')
_P = ParamSpec('_P')
_T_ANY: type[Any] = cast(type[Any], Any)

# region OS
OS_W11 = "W11"
OS_LINUX = "Linux"
OS_WSL = "WSL"
OS_OTHER = "Other" 

def detect_os():
  sysname = platform.system()
  if sysname == "Windows": return OS_W11
  elif sysname == "Linux":
    release = platform.release().lower()
    if "microsoft" in release or "wsl" in release: return OS_WSL
    return OS_LINUX
  else:
    return OS_OTHER
# # endregion

# region Safe typecasting
def safe_float(o, default: Optional[float] = None) -> Optional[float]:
  result: float | None
  if o is None: return default
  if isinstance(o, str):
    o = o.removesuffix("°c")
    o = o.removesuffix("%")
  try: result = float(o)
  except: result = default
  return result


def coerce_float(o, default: float = 0.0) -> float: return _ if (_ := safe_float(o, default)) else default
def safe_int(o, default: Optional[int] = None) -> Optional[int]: return int(_) if (_ := safe_float(o, default)) else default
def coerce_int(o, default: int = 0) -> int: return int(_) if (_ := safe_float(o, default)) else default


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
# deepdict = lambda: defaultdict(deepdict)
deepdict: Callable[[], DefaultDict[Any, Any]] = lambda: defaultdict(deepdict)

def deepget(path: str, d: dict, default=None):
  if '/' in path and path not in d.keys():
    _ = dict(d)
    for pp in path.split('/'):
      _ = _.get(pp)
      if not _: break
    return _ if _ else default
  return d.get(path, default)


def deepget_int(path: str, d: dict, default: int | None = None) -> int | None:
  """ Returns int at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, int) else default


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
KEYS_DROP = ['api', 'adapi', 'AD']
KEYS_FIRST = ['name', 'path']

def _isstring(o) -> bool:
  relatives = {type(o).__qualname__}
  relatives |= {c.__qualname__ for c in o.__class__.__mro__}
  return bool({'y2list', 'str', 'y2topic', 'y2path', 'ADBase'} & relatives)
_islist = lambda o: not _isstring(o) and isinstance(o, (list, set))
_isdict = lambda o: not _isstring(o) and (isinstance(o, (dict, defaultdict, UserDict)) or hasattr(o, 'as_dict') or (hasattr(o, 'data') and isinstance(o.data, dict)))
_isnumber = lambda o: isinstance(o, (float, int))

def sanitize_list(o) -> list:
  result = []
 
  for e in sorted(o, key=lambda x: str(x)):
    if _isdict(e): _ = sanitize_dict(e)
    elif _islist(e): _ = sanitize_list(e)
    elif _isnumber(e): _ = e
    else: _ = str(e) if e else None
    result.append(_)
  return result

def sanitize_dict(o) -> dict:
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
    elif _isdict(v): _ = sanitize_dict(v)
    elif _islist(v): _ = sanitize_list(v)
    elif _isnumber(v): _ = v
    else: _ = str(v) if v else None
    result[str(k)] = _
  return result

def dict_sanitize(data: dict | list, sort_keys=False) -> dict | list:
  """Convert nested complex data types for json.dumps or yaml.dumps"""
  if _islist(data): return sanitize_list(data)
  elif _isdict(data): return sanitize_dict(data)
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

# region Loggin and Time helpers: now_ts, now_str
"""Logging"""
def pfy(object) -> str:
    """Pretty format object using Rich pretty printing."""
    from io import StringIO
    import contextlib
    
    # Capture Rich pretty print output
    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=False, width=80)
    temp_console.print(Pretty(object, indent_guides=True, max_length=10, max_string=80))
    result = string_io.getvalue()
    
    # Return with leading newline for compatibility
    return "\n" + result if not result.startswith("\n") else result
def slugify(o) -> str:
  """Converts any object to string, then slugifies it"""
  return re.sub(r'[^a-zA-Z0-9_]', '_', str(o).lower())
# endregion3333333333333333333333333333333333333333333333


# region Tracing decorators
TracerAction: TypeAlias = Literal['before', 'after', 'instead']

TA_BEFORE: TracerAction = 'before'
TA_AFTER: TracerAction = 'after'
TA_INSTEAD: TracerAction = 'instead'
TAs: list[TracerAction] = [TA_BEFORE, TA_AFTER, TA_INSTEAD]


# def _tracer(tracer: Callable[..., Any] | None = None, action: TracerAction | None = None) -> Callable:
def _tracer(tracer: Optional[Callable[..., Any]] = None, action: Optional[TracerAction] = None) -> Callable:
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
  def __init__(self, o=None): 
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)


class y2eid:
  ns: str
  domain: str
  slug: y2slug
  default_ns: ClassVar[str] = 'yala'
  default_domain: ClassVar[str] = 'entity'


  def __init__(self, o: Any, ns: Optional[str] = None, **kw):
    ns = ns or self.default_ns
    if not o: return
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
  def entity_id(self) -> str: return f"{self.domain}.{self.slug}"
  @property
  def seid(self): return str(self)

# endregion


# region PCP - Pretty Colored Print and colorize - utility
class _TColorHack(type):
  """Metaclass for TColor to support dictionary-like access and Rich style mapping."""
  def __getitem__(cls, key): return getattr(cls, str(key), None)
  def __contains__(cls, key): return hasattr(cls, str(key))

  def print(cls):
    """Print all available colors using Rich."""
    table = Table(title="Available Colors", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Style", style="green")
    table.add_column("Preview")
    
    for name in dir(cls):
      if not name.startswith('_'):
        style = getattr(cls, name)
        if isinstance(style, str) and not name in ['print']:
          table.add_row(name, style, Text(f"Sample {name}", style=style))
    
    console.print(table)


class TColor(metaclass=_TColorHack):
  """Color definitions using Rich style strings."""
  # Text colors
  NONE = "default"                # No color (text)
  DIM = "dim"                     # Dim gray (text)
  BRIGHT = "bright_cyan bold"     # Bright cyan (text)
  BW = "bright_white bold"        # Bright white (text)
  DW = "white"                    # Dark white (text)
  INFO = "bright_blue bold"       # Bright blue (text, for info messages)
  
  # Background colors
  WHITE = "black on white"        # Black on White (background)
  YELLOW = "black on yellow"      # Black on Yellow (background)
  RED = "black on red"            # Black on Red (background)
  BLUE = "black on blue"          # Black on Blue (background)
  GREEN = "black on green"        # Black on Green (background)

  # Gray scale
  GRAY0 = "grey23"                # Darkest gray (text)
  GRAY1 = "grey27"                # Gray (text)
  GRAY2 = "grey50"                # Gray (text)
  GRAY3 = "grey58"                # Gray (text)
  GRAY4 = "grey70"                # Lightest gray (text)

  # Bright/Dark color pairs
  BY = "bright_yellow bold"       # Bright yellow (text)
  DY = "yellow"                   # Dark yellow (text)
  BG = "bright_green bold"        # Bright green (text)
  DG = "green"                    # Dark green (text)
  DB = "blue"                     # Dark blue (text)
  BC = "bright_cyan bold"         # Bright cyan (text)
  DC = "cyan"                     # Dark cyan (text)
  BM = "bright_magenta bold"      # Bright magenta (text)
  DM = "magenta"                  # Dark magenta (text)
  BR = "bright_red bold"          # Bright red (text)
  DR = "red"                      # Dark red (text)
  BP = "bright_magenta bold"      # Bright purple (text)
  DP = "purple"                   # Dark purple (text)
  BO = "rgb(255,165,0) bold"      # Bright orange (text)
  DO = "rgb(205,115,0)"           # Dark orange (text)
  PINK = "rgb(255,192,203) bold"  # Bright pink (text)
  DPINK = "rgb(199,21,133)"       # Dark pink (text)
  BGOLD = "rgb(255,215,0) bold"   # Bright gold (text)
  DGOLD = "rgb(184,134,11)"       # Dark gold (text)

  # Aliases
  ORANGE = BO                      # Bright orange (text)
  PURPLE = BP                      # Bright purple (text)

  # White on color backgrounds
  WRED = "white on red"           # White on Red (background)
  WBLUE = "white on blue"         # White on Blue (background)
  WGREEN = "white on green"       # White on Green (background)
  WGRAY = "black on bright_white" # Black on Light Gray (background)
  WPINK = "black on magenta"      # Black on Pink (background)
  WPURPLE = "white on magenta"    # White on Purple (background)
  WYELLOW = "black on yellow"     # Black on Yellow (background)


def pcp(*a: str | List[Any] | Tuple[Any, ...], **kw: Any) -> str:
  """
  Pretty colored print using Rich. Supports two kinds of input:
    level, msg: compatible with default logger
    [args]: used by self.Dargs to colorize output
  Returns: formatted string (for compatibility)
  
  Parameters:
    verbose: adds pfy(kwargs) to output
    silent: suppresses local print output
    return_text: returns Rich Text object instead of string
  """
  if len(a) == 1 and isinstance(a[0], tuple): a = tuple(a[0])
  
  verbose = kw.pop('verbose', False)
  silent = kw.pop('silent', False)
  return_text = kw.pop('return_text', False)
  level = kw.pop('level', None)
  
  # Build Rich Text object
  text = Text()
  
  if 'msg' in kw:
    msg = kw.get('msg')
    text = _colorize_log_rich(msg=msg, level=level)
    if a: 
      text.append(" ")
      text.append(_colorize_list_rich(a))
  else:
    text = _colorize_list_rich(a)
  
  if kw and verbose:
    text.append("\n")
    # Convert Pretty object to string for Text.append()
    from io import StringIO
    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=False)
    temp_console.print(Pretty(kw), end="")
    text.append(string_io.getvalue(), style="dim")
  
  # Print using Rich console if not silent
  if not silent:
    console.print(text)
  
  # Return Text object or string for compatibility
  if return_text:
    return text
  else:
    # Return plain string for backward compatibility
    from io import StringIO
    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=False)
    temp_console.print(text)
    return string_io.getvalue().rstrip()


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
    if 'python3' in fi.filename: return True # !!! Ignoring all python3 libraries
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

  if frame is None: 
    print(f"\tframe is None")
    return None

  if not is_traced(func_name): 
    print(f"\tis_traced({func_name}) is False")
    return None
  module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
  if not is_traced(module) or not is_traced(f"{module}.{func_name}"): 
    print(f"\tis_traced({module}.{func_name}) is False")
    return None

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
  #else: raise ValueError(f"Invalid log_colored call: {msg} {level} {args}")
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


def _colorize(text: str, colorcode: str, fmt=None) -> str:
  """Apply Rich style to text (legacy wrapper for backward compatibility)."""
  text = str(text)
  
  # Handle formatting
  right, pad = False, ''
  if fmt:
    if fmt[0] in "<>": 
      right = fmt[0] == '>'
      fmt = fmt[1:]
    maxlen = coerce_int(fmt)
    text = text[-maxlen:] if right else text[0:maxlen]
    if (l := len(text)) < maxlen: 
      pad = ' ' * (maxlen - l)
  
  # Apply style using Rich
  if colorcode == 'NONE' or not colorcode:
    styled_text = text
  else:
    # Convert old color codes to Rich styles if needed
    if hasattr(TColor, colorcode):
      style = getattr(TColor, colorcode)
    else:
      style = colorcode
    
    rich_text = Text(text, style=style)
    
    from io import StringIO
    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=False, legacy_windows=False)
    temp_console.print(rich_text, end="")
    styled_text = string_io.getvalue()
  
  return pad + styled_text if right else styled_text + pad


def _colorize_log_rich(msg, level=None, *args):
  """Create Rich Text object with appropriate styling for log messages."""
  text = Text()
  
  if isinstance(msg, (list, tuple)):
    return _colorize_list_rich(msg)
  elif level:
    # Map log levels to Rich styles
    level_styles = {
      'CRITICAL': ('bright_red bold', 'bright_white bold'),
      'ERROR': ('bright_red bold', 'bright_white'),
      'WARN': ('bright_yellow bold', 'bright_white'),
      'WARNING': ('bright_yellow bold', 'bright_white'),
      'INFO': ('blue', 'bright_blue'),
      'DEBUG': ('dim', 'dim')
    }
    
    style1, style2 = level_styles.get(level, ('dim', 'default'))
    text.append(f"[{level}] ", style=style1)
    text.append(str(msg), style=style2)
    
    for arg in args:
      text.append(" ")
      text.append(str(arg))
  else:
    text.append(str(msg))
  
  return text


def _colorize_list_rich(l: List[Union[str, Any]]):
  """Convert list to Rich Text with color styling."""
  text = Text()
  current_style = None
  
  for e in [e for e in l if e is not None]:
    e_str = str(e)
    
    # Check if it's a color/style name
    if hasattr(TColor, e_str):
      current_style = getattr(TColor, e_str)
      continue
    
    # Handle separators
    if e_str and e_str[0] in "./":
      e_str = e_str[1:]
      separator = ""
    else:
      separator = " " if len(text) > 0 else ""
    
    # Append with style
    if separator:
      text.append(separator)
    
    if current_style:
      text.append(e_str, style=current_style)
    else:
      text.append(e_str)
  
  return text


class PrettyColoredFormatter(logging.Formatter):
  """Custom formatter using Rich for colored output."""
  def format(self, record):
    """Format log record with Rich styling."""
    verbose = getattr(record, 'verbose', False)
    level = record.levelname
    msg = super().format(record)  # Default formatting for the message

    # Apply Rich colorization
    text = _colorize_log_rich(msg, level)
    if hasattr(record, 'args') and record.args:
      args = list(record.args) if not isinstance(record.args, list) else record.args
      text.append(" ")
      text.append(_colorize_list_rich(args))

    kwargs = getattr(record, 'kwargs', None)
    if verbose and isinstance(kwargs, dict):
      text.append("\n")
      # Convert Pretty object to string for Text.append()
      from io import StringIO
      string_io = StringIO()
      temp_console = Console(file=string_io, force_terminal=False)
      temp_console.print(Pretty(kwargs), end="")
      text.append(string_io.getvalue(), style="dim")

    # Convert Rich Text to string
    from io import StringIO
    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=False)
    temp_console.print(text, end="")
    return string_io.getvalue()


class PrettyColoredHandler(logging.StreamHandler):
  def emit(self, record):
    silent = getattr(record, 'silent', False)
    if not silent:
      super().emit(record)


def _fmt(*a, severity: str = 'Debug', **kw) -> str:
  if severity.upper() == 'DEBUG':
    result = dpcp(*a, rules=TRACE_RULES or {}, conditional=True, **kw)
  else:
    result = dpcp(*a, conditional=False, severity=severity, **kw)
  # dpcp now returns empty string instead of None, but let's be safe
  return result if result else ''


class _LogColorizer(logging.Formatter):
  """Rich-based formatter for log colorization."""
  def format(self, record: logging.LogRecord) -> str:
    args = [record.msg]
    if record.args is not None: 
      args.extend(record.args)
    result = _fmt(*args, severity=record.levelname)
    return result
# endregion


# region Logger
# @@      mixin class                                                           == 
class mixin: pass

# ^~            Logger                                            
TRACE_RULES: dict = {}

_logger = logging.getLogger('gppu')
_logger.setLevel(logging.DEBUG)  # Ensure logger level is set to DEBUG

# _sh = logging.FileHandler('gppu_logger.log', mode='a')  # Use FileHandler to log to a file
# _sh.setLevel(logging.DEBUG)
# _sh.setFormatter(_LogColorizer())
# _sh.addFilter(lambda record: not getattr(record, '_should_filter', False))
# _logger.addHandler(_sh)

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


# Use Rich handler for better formatting
_rich_handler = RichHandler(
    console=console,
    show_time=False,
    show_path=False,
    markup=True,
    rich_tracebacks=True,
    tracebacks_show_locals=True
)
_rich_handler.setLevel(logging.DEBUG)

# Also keep a traditional handler with our custom formatter for compatibility
_sh = logging.StreamHandler()
_sh.setLevel(logging.DEBUG)
_sh.setFormatter(_LogColorizer())
_sh.addFilter(_EmptyMessageFilter())

# Use Rich handler by default, traditional handler commented out to avoid duplication
_logger.addHandler(_rich_handler)
# _logger.addHandler(_sh)  # Uncomment if you need traditional output



# _sh.setFormatter(logging.Formatter('%(message)s'))

def init_logger(name: str = 'gppu', trace_rules: dict | None = None) -> None:
  """Initialize global logger with a specific name and optional trace rules."""
  global _logger, TRACE_RULES
  if trace_rules is not None:
    TRACE_RULES = trace_rules
  Logger.trace_rules = TRACE_RULES
  new_logger = logging.getLogger(name)
  new_logger.setLevel(logging.DEBUG)
  new_logger.handlers = []
  new_logger.addHandler(_sh)
  _logger = new_logger
  for cls in list(mixin_Logger.__subclasses__()):
    cls._logger = _logger.getChild(cls.__name__)
    for n, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)):
      setattr(cls, n, staticmethod(partial(fn, logger=cls._logger)))

def Debug(*a, logger=None, **kw): (logger or _logger).debug(*a, **kw)
def Info(*a, logger=None, **kw): (logger or _logger).info(*a, **kw)
def Warn(*a, logger=None, **kw): (logger or _logger).warning(*a, **kw)
def Error(*a, logger=None, **kw): (logger or _logger).error(*a, **kw)
def Dump(filename: str, data={}):
  """ Saves data object to yml file in trace folder """
  if '.' not in filename or not filename.endswith('.yml'): filename += '.yml'
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


class protocol_Logger(Protocol):
  Debug: Callable[..., Any]
  Info : Callable[..., Any]
  Warn : Callable[..., Any]
  Error: Callable[..., Any]
  Dump : Callable[..., Any]


class mixin_Logger(protocol_Logger, mixin):
  _logger: logging.Logger

  @classmethod
  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    cls._logger = _logger.getChild(cls.__name__)
    for name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn),
                     ('Error', Error), ('Dump', Dump)):
      setattr(cls, name, staticmethod(partial(fn, logger=cls._logger)))

  def __init__(self, *a, **kw):
    super(mixin_Logger, self).__init__(*a, **kw)    # ← no warning
    # instance shortcuts re-use the class-level bound functions
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'):
      setattr(self, name, getattr(self.__class__, name))
# endregion


# ==                              DC - DataClass                              ==                                           
# region DC - Pseudo-DataClass
def _eval_with_extras(expr: str, frm: FrameType, extra_modules: list[ModuleType] = []):
  ns = {}
  ns.update(frm.f_globals or {})
  ns.update(frm.f_locals or {})
  for m in extra_modules:
    if isinstance(m, ModuleType): ns[m.__name__] = m
    elif isinstance(m, dict): ns.update(m)
    else: ns[type[m].__name__] = m
  return eval(expr, ns, ns)


def _resolve_type(name: str, *, extra_modules: list[ModuleType] | None = None) -> type[Any]:
  if isinstance(name, type): return name
  if hasattr(builtins, name): return getattr(builtins, name)

  frm = sys._getframe(1)
  try:
    # evaluated = eval(name, frm.f_globals, frm.f_locals)
    # Convert PEP 604 UnionType or typing.Union to typing.Union[...] form
    evaluated = _eval_with_extras(name, frm, extra_modules or [])
    if isinstance(evaluated, type): return evaluated
    if isinstance(evaluated, UnionType): return cast(type[Any], Union[evaluated.__args__])
    if getattr(evaluated, "__origin__", None) is Union: return evaluated    
  except Exception as e:
    # print(f"Error evaluating type name: {name}\n{e}")    
    return _T_ANY  # Fallback to Any if evaluation fails

  try:
    typ = ForwardRef(name)._evaluate(frm.f_globals, frm.f_locals, recursive_guard=frozenset())
    if isinstance(typ, type):
      return typ
  except NameError as ne:
    # print(f"Error evaluating type name: {name}\n{ne}")
    return _T_ANY  # Fallback to Any if evaluation fails

  if isinstance(obj := locate(name), type): return obj

  if name in frm.f_globals and isinstance(frm.f_globals[name], type): return frm.f_globals[name]
  caller_mod = frm.f_globals.get('__name__')
  auto = [sys.modules[caller_mod]] if caller_mod else []
  for mod in (extra_modules or []) + auto:
    if hasattr(mod, name) and isinstance(obj := getattr(mod, name), type): return obj

  return _T_ANY


def safe_isinstance(obj: Any, hint: Any, *, extra_modules: list[ModuleType] | None = None, default=False) -> bool:
  if isinstance(hint, str): hint = _resolve_type(hint, extra_modules=extra_modules)

  if hint is Any: return True

  origin = get_origin(hint)
  if origin is None: return isinstance(obj, hint)

  # --- generics -----------------------------------------------------------
  if origin is Union: return any(safe_isinstance(obj, h, default=default, extra_modules=extra_modules) for h in get_args(hint))

  if origin in (list, tuple, set, frozenset):
    if not isinstance(obj, origin): return False
    (sub,) = get_args(hint) or (Any,)
    return all(safe_isinstance(i, sub, default=default, extra_modules=extra_modules) for i in obj)

  if origin is dict:
    if not isinstance(obj, dict): return False
    k_t, v_t = get_args(hint) or (Any, Any)
    return (all(safe_isinstance(k, k_t, default=default, extra_modules=extra_modules) for k in obj.keys()) and
            all(safe_isinstance(v, v_t, default=default, extra_modules=extra_modules) for v in obj.values()))

  return isinstance(obj, origin)


def _typ2str(typ: object) -> str: return getattr(typ, "__name__", str(typ))


class DC(UserDict): # DataClass
  """
    DC is a dict that allows access to dict elements as properties.
    Only elements returned by _get_all_annotations cam be used as properties. 
    DC dynamically adds getter and setter for annotated properties that point to main dict.

    "__init__" is final
    All descendents must use init()
  """
  class _Policy:
    PROHIBITED_ATTRS  = {'data'}
    ALLOWED_ATTRS     = set()
    PROHIBITED_TYPES  = {Callable}
    ALLOWED_TYPES     = {str, list, dict, set, int, float, bool}

    @classmethod
    def _names(cls, types): return {getattr(tp, "__name__", str(tp)) for tp in types}
  
    @classmethod
    def is_allowed(cls, attr: str, hint: object) -> bool:
      st = _typ2str(hint)
      if (attr in cls.ALLOWED_ATTRS or st in cls._names(cls.ALLOWED_TYPES)): return True
      if (attr.startswith('_') or attr in cls.PROHIBITED_ATTRS or callable(hint) or st in cls._names(cls.PROHIBITED_TYPES)): return False
      return True


  @classmethod
  def _policy(cls) -> type[_Policy]:
    return getattr(cls, 'Policy', cls._Policy)


  def __init_subclass__(cls, **kw) -> None:
    super().__init_subclass__(**kw)

    policy = cls._policy()

    annotations = [(n, t) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items()]
      
    mro = [(n, t) for n, t in annotations if policy.is_allowed(n, t)]
    # print(f"{cls} has\n\t{[_typ2str(t) for _, t in _get_all_annotations(cls)]}\n\t{[_typ2str(t) for _, t in mro]}")
    # pp([_typ2str(t) for _, t in _get_all_annotations(cls)])
    # pp([_typ2str(t) for _, t in mro])
    # pp([(_typ2str(t), resolve_type(t)) for _, t in mro])
    for aname, atype in mro:
      def getter(self, name=aname): 
        if not (result := self.data.get(name)):
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if value and not safe_isinstance(value, type_hint, default=True, extra_modules=[_owner_mod]): 
          raise TypeError(f"Expected type {type_hint} for {name}, got {type(value)} instead.")
        
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  @final
  def __init__(self, **kw):
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data
    if hasattr(self, 'init') and callable(self.init): self.init()


  def __lt__(self, other): return str(self) < str(other)


  @abstractmethod
  def init(self): ...
# endregion


