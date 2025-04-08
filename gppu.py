from __future__ import annotations

VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '24'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

import yaml
import re
import logging
import inspect
import pprint
from functools import partialmethod
from string import Template

from pydantic import BaseModel
from typing import Any, Dict, List, Union, Optional, Callable, ClassVar
from collections import defaultdict, UserDict, UserList
import os.path


# region Logging
class Logger:
  """
  Core Logger class that implements all logging functionality
  Can be used both globally and injected into classes
  """

  def __init__(self, name: str = "gppu", level: str = "INFO", trace_rules: Dict[str, bool] = None, trace_folder: str = "."):
    self.name = name
    self._logger = logging.getLogger(name)
    self._trace_rules = trace_rules or {}
    self._trace_folder = trace_folder

    self._logger.setLevel(getattr(logging, level))

  @staticmethod
  def _is_debug(rules: Dict[str, bool]) -> bool:
    if not rules: return True

    frame = inspect.currentframe()
    if frame is None: return False

    frame = frame.f_back
    if frame is None: return False

    frame_info = inspect.getframeinfo(frame)
    func_name = frame_info.function
    filename = frame_info.filename
    module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]

    if rules.get(func_name, False): return True
    if rules.get(module, False): return True

    if 'self' in frame.f_locals:
      class_name = frame.f_locals["self"].__class__.__name__
      if rules.get(f"{class_name}.{func_name}", False): return True
      if rules.get(class_name, False): return True

    return rules.get('all', False)

  @staticmethod
  def _msg(*a, severity=None, **kw):
    """Format args into a string message with optional severity prefix"""
    parts = []

    if severity: parts.append(f"[{severity}]")

    for arg in a:
      if isinstance(arg, (list, dict, tuple)): parts.append(pprint.pformat(arg, indent=2))
      else: parts.append(str(arg))
    for k, w in kw.items():
      parts.append(f"{k}={w}")

    return " ".join(parts)

  def _log(self, level, *a, **kw):
    msg = self._msg(*a, severity=level, **kw)
    self._logger.log(level, msg)

  def Debug(self, *a, **kw):
    if self._is_debug(self._trace_rules):
      self._logger.debug(self._msg(*a, **kw))

  Info = partialmethod(_log, level=logging.INFO)
  Warn = partialmethod(_log, level=logging.WARNING)
  Error = partialmethod(_log, level=logging.ERROR)

  def Fatal(self, *a, **kw):
    msg = self._msg(*a, **kw)
    self._log(logging.CRITICAL, msg)
    raise RuntimeError(msg)


class LoggerMixin:
  logger: Logger

  def __init__(self, *a, logger: Optional[Logger] = None, **kw):
    self.logger = logger or Logger(self.__class__.__name__)
    super().__init__(*a, **kw)
 

  def Debug(self, *a, **kw): self.logger.Debug(*a, **kw)
  def Info(self, *a, **kw): self.logger.Info(*a, **kw)
  def Warn(self, *a, **kw): self.logger.Warn(*a, **kw)
  def Error(self, *a, **kw): self.logger.Error(*a, **kw)
  def Fatal(self, *a, **kw): self.logger.Fatal(*a, **kw)
  # def _log(self, level, *a, **kw):
  #   self.logger._log(level, *a, **kw)


  # Debug = lambda self, *a, **kw: self.logger.Debug(*a, **kw)
  # Info = partialmethod(_log, level=logging.INFO)
  # Warn = partialmethod(_log, level=logging.WARNING)
  # Error = partialmethod(_log, level=logging.ERROR)
  # Fatal = lambda self, *a, **kw: self.logger.Fatal(*a, **kw)


_GLOBAL_LOGGER = Logger()
# def Debug(*a, **kw): _GLOBAL_LOGGER.Debug(*a, **kw)
# def Info(*a, **kw): _GLOBAL_LOGGER.Info
# def Warn(*a, **kw): _GLOBAL_LOGGER.Warn
# def Error(*a, **kw): _GLOBAL_LOGGER.Error
# def Fatal(*a, **kw): _GLOBAL_LOGGER.Fatal(*a, **kw)
    
Debug: Callable = _GLOBAL_LOGGER.Debug 
Info: Callable = _GLOBAL_LOGGER.Info
Warn: Callable = _GLOBAL_LOGGER.Warn
Error: Callable = _GLOBAL_LOGGER.Error
Fatal: Callable = _GLOBAL_LOGGER.Fatal
# endregion


# region Dict utils: deepget, dict_all_paths
deepdict = lambda: defaultdict(deepdict)
def deepget(path: str, d: dict, default: Any = None) -> Any:
  if '/' in path and path not in d.keys():
    _ = dict(d)
    for pp in path.split('/'):
      _ = _.get(pp)
      if not _: break
    return _ if _ else default
  return d.get(path, default)


def deepget_int(path: str, d: dict, default: Optional[int]) -> Optional[int]:
  """ Returns int at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, int) else default


def deepget_list(path: str, d: dict, default: list = []) -> list:
  """ Returns list at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, list) else default


def deepget_dict(path: str, d: dict, default: dict = {}) -> dict:
  """ Returns dict at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, dict) else default

# endregion

# def _init_default_logger():
#   l = logging.getLogger('gppu')
#   sh = logging.StreamHandler(stream=sys.stdout)
#   sh.setLevel(logging.DEBUG)
#   sh.setFormatter(logging.Formatter('%(message)s'))
#   l.addHandler(sh)
#   l.setLevel(logging.DEBUG)
#   return l
#
# logger = _init_default_logger()
#


class YAMLConfig(BaseModel):
  keys_first: List[str] = ["name", "path"]
  keys_drop: List[str] = ["api", "adapi", "AD"]
  keys_force_string: List[str] = ["parent"]


class Config:
  arbitrary_types_allowed = True


# Custom YAML representer for tuples
def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
  """Custom representer for tuples in YAML"""
  return dumper.represent_dict(dict(enumerate(data)))


def dict_to_yml(data: Union[Dict, List], filename: str, config: Optional[YAMLConfig] = None) -> None:
  """
  Save dictionary to YAML file with proper indentation and ordering

  Args:
    data: Dictionary or list to serialize
    filename: Output file path
    config: Optional YAML configuration settings
  """
  if not data or not filename:
    return

  if config is None:
    config = YAMLConfig()

  # Use custom dumper for proper indentation
  class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
      return super().increase_indent(flow, False)

  # Register custom representers
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, _tuple_representer)

  try:
    with open(filename, 'w+', encoding="utf-8") as f:
      yaml.dump(data, f, indent=2, Dumper=IndentedDumper, sort_keys=False, width=2147483647)
  except Exception as err:
    error_msg = f"Error dumping {filename}: {err}"
    with open(f"{filename}_error.txt", 'w+', encoding='utf-8') as ferr:
      ferr.write(error_msg)
    raise RuntimeError(error_msg)


def dict_from_yml(filename: str) -> Dict:
  """
  Load dictionary from YAML file with support for !include directive

  Args:
    filename: Path to YAML file

  Returns:
    Dictionary loaded from YAML
  """
  if not os.path.exists(filename):
    raise FileNotFoundError(f"YAML file not found: {filename}")

  yml_root = os.path.dirname(filename)

  # Custom constructor for handling !include directive
  def yml_include(loader, node):
    include_path = node.value
    if not include_path.startswith('/'):
      include_path = os.path.join(yml_root, include_path)

    with open(include_path, "r", encoding='utf-8') as f:
      return yaml.safe_load(f)

  # Register custom constructors
  yaml.add_constructor("!include", yml_include, Loader=yaml.SafeLoader)

  try:
    with open(filename, "r", encoding='utf-8') as f:
      return yaml.safe_load(f) or {}
  except UnicodeDecodeError as err:
    with open(filename, "r", encoding="latin-1") as f:
      return yaml.safe_load(f) or {}


def dict_template_populate(o, data: dict = {}, excludes:list = []) -> Any:
  """ 
    Returns new dictionary, copy of o with all templatable elements filled-in from data 
    
    This function is recursive

    Keys with value == 'DEL' are removed from result
    Keys with '$' in value are treated as templates and filled-in from data
  """
  def __tp(o, data: dict) -> Any:
    result: Any = None
    if not data: data = {}

    elif isinstance(o, dict):
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
        _ = Template(str(o)).safe_substitute(data)
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
  result = __tp(_, data)
  return result
# endregion


# region y2xxx
# xx                                                                                        
# xx y2list, y2path and y2slug                                                              
# xx                                                                                        
def any2list(o, token: Optional[str] = None) -> list:
  """ y2list-based: y2path, y2slug"""
  result = []
  if o:
    if hasattr(o, 'data'): o = o.data
    if isinstance(o, (list, tuple)): result = [_ for _ in o if _]
    elif token: result = str(o).split(token)
    else: result = re.findall('[a-zA-Z0-9]+', str(o))
  return result


class y2list(UserList):
  data: List[Any]
  token: str

  def __init__(self, o: Optional[Any] = None, token: str = "") -> None:
    super().__init__()
    self.token = token
    self.data = any2list(o, self.token)



  def __str__(self): return self.token.join(self.data)
  def __repr__(self): return self.token.join(self.data)
  def __hash__(self): return hash(str(self))
  def __eq__(self, other: Any) -> bool:
    if hasattr(other, 'data'): return self.data == other.data
    else: return str(self) == str(other)


  def upper(self): return str(self).upper()
  def lower(self): return str(self).lower()
  def encode(self, encoding='utf-8', errors='strict'): return str(self.data).encode(encoding, errors)
  def iadd(self, o): self.data += any2list(o)
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
      self.data = any2list(str(self).replace(ix, ''))
      return self.token.join(any2list(ix))


  def popprefix(self, ix):
    if self.startswith(ix):
      if '_' in ix and self.token != '_': ix = ix.replace('_', self.token)
      elif '/' in ix and self.token != '/': ix = ix.replace('/', self.token)
      self.data = any2list(str(self).replace(ix, ''))
      return self.token.join(any2list(ix))


  def popxfix(self, ix): return self.popsuffix(ix) or self.popprefix(ix)


class y2path(y2list):
  def __init__(self, *a):
    y2list.__init__(self, o=a, token='/')


class y2topic(y2path):
  def is_wildcard(self) -> bool: return bool(set(self.data) & {"#", "+"})


class y2slug(y2list):
  def __init__(self, o=None): 
    if '@' in str(o): o = str(o).split('@', 1)[0]
    y2list.__init__(self, o, token='_')


class y2eid:
  ns: str

  def __init__(self, o=None, ns: Optional[str] = None):
    if not o: return
    if isinstance(o, y2eid): s = str(o)
    elif isinstance(o, dict): s = str(o.get('entity_id',""))
    elif isinstance(o, str): s = o
    elif hasattr(o, 'entity_id') and hasattr(o, 'namespace'): s = f"{o.entity_id}@{o.namespace}"
    elif hasattr(o, 'entity_id') and hasattr(o, 'ns'): s = f"{o.entity_id}@{o.ns}"
    elif hasattr(o, 'seid'): s = o.seid
    else: raise ValueError

    if '.' in s: self.domain, s = s.split('.',1)
    if '@' in s:
      if ns: raise ValueError(f"Cannot set ns twice: {self.ns} {s}")
      s, self.ns = s.rsplit('@',1)

    if not self.ns:
      if ns: self.ns = ns
      else: raise ValueError(f"Missing namespace: {o} {ns}")

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
  def eid(self) -> str: return str(self)
  @property
  def seid(self): return str(self)

# endregion

# ==                              YData                                           
# region YData
import builtins
from typing import get_origin, get_args
from typing import Annotated, TypeVar

_TMRO = list[tuple[str, list[str]]]

def _get_all_annotations(cls) -> _TMRO:
  """Return list of annotations that are allowed to be used as properties"""
  PROHIBITED_ATTRS = ['data', 'AD', 'yapi', 'adapi']
  ALLOWED_ATTRS: list[str] = []
  # ALLOWED_ATTRS = ['parent']
  ALLOWED_TYPES = {str, int, float, bool, dict, list, set, y2eid, y2topic}
  # ALLOWED_TYPES_STR = {t.__name__ for t in ALLOWED_TYPES}
  PROHIBITED_TYPES = {Callable}
  PROHIBITED_TYPE_NAMES = ['Phase']

  def check_attr(n, t) -> bool:
    if get_origin(t) is Annotated:
      metadata = get_args(t)[1:]
      if 'YData.ignore' in metadata:
        return False
      t = get_args(t)[0]      
    if n in ALLOWED_ATTRS: return True
    if n in PROHIBITED_ATTRS or n[0] == '_': return False
    if t in ALLOWED_TYPES: return True
    if t in {t.__name__ for t in ALLOWED_TYPES}: return True
    if getattr(t, '__name__', None) in {t.__name__ for t in ALLOWED_TYPES}: return True
    return False

  def type_to_slist(t) -> list[str]:
    if hasattr(t, '__name__'): t = t.__name__
    if '|' in t:
      result = [x.strip() for x in t.split('|')]
    else:
      result = [t]
    return result

  _ = [(n, ts) for c in cls.mro() if hasattr(c, '__annotations__')
        for n, t in c.__annotations__.items()
        for ts in [type_to_slist(t)]
        if any(check_attr(n, t_str) for t_str in ts)]

  return _


class YData(UserDict):
  """
  YData is a dict that allows access to dict elements as properties.
  Only elements returned by _get_all_annotations cam be used as properties. 
  YData dynamically adds getter and setter for annotated properties that point to main dict.
  """

  _mro: _TMRO
  def __init_subclass__(cls, **kw) -> None:
    def safe_isinstance(o: object, typ: type | str | list[str], default: bool = False) -> bool: # type: ignore[return]
      """ Safe version of isinstance. Use with default=True to be more permissive """
      if not isinstance(typ, list): typ = list[typ]
      result = None
      for t in typ:
        if isinstance(t, str):
          otype = str(type(o)).split("'")[1].rpartition('.')[2]
          if result is None:
            result = bool(otype == t)
        else:
          if t in {Any}: return True
          problematic = {Union, TypeVar}
          safe = {int, float, str, dict, list}
          if t in problematic: continue 
          if set(get_args(t)) - safe: continue # ! Unsafe type detected
          if get_origin(t) in problematic: continue
          if result is None:
            result = isinstance(o, t)
        if result is not None: return result
      if result is None: return default



    super().__init_subclass__(**kw)
    mro = _get_all_annotations(cls)
    cls._mro = mro
    Debug("DG", cls.__name__, *[x for tup in mro for x in ['DIM', '|'.join(tup[1]) + ':', 'INFO', tup[0]]])
    for aname, atype in mro:
      if isinstance(getattr(cls, aname, None), property): continue
      def getter(self, name=aname, type_hint=atype):
        if not hasattr(self, 'data'): raise RuntimeError(f"YData object {name} {type_hint} not initialized'")
        convs = []
        for th in type_hint:
          _ = getattr(builtins, th, None) or globals().get(th, None)
          if _: convs.append(_)

        # conv = getattr(builtins, type_hint, None) or globals().get(type_hint, None)
        # if conv is None: raise TypeError(f"Failed to get default for {name} of type {type_hint}: {e}")
        if not self.data.get(name, None):
          try:
            default = convs[0]()
            self.data[name] = default
            return default
          except Exception as e:
            raise TypeError(f"Failed to get default for {name} of type {type_hint}: {e}")
        value = self.data[name]

        for conv in convs:
          if isinstance(value, conv): break
        else:
          try:
            converted = convs[0](value)
            self.data[name] = converted
            return converted
          except Exception as e:
            raise TypeError(f"Failed to convert {name} to {type_hint}: {e}")

        return value
      def setter(self, value, name=aname, type_hint=atype):
        if not hasattr(self, 'data'): raise RuntimeError(f"YData {cls} object not initialized'")

        if value and not safe_isinstance(value, type_hint, default=True):
          raise TypeError(f"Expected type {type_hint} for {name}, got {type(value)} instead.")

        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  def __init__(self, *a, **kw):
    UserDict.__init__(self, kw.pop('data', {}), **kw)
    import builtins
    for n, tlist in self._mro:
      if n in self.data:
        last_exception = None
        for t in tlist:
          resolved = getattr(builtins, t, None) or globals().get(t, None)
          if resolved is None:
            continue
          try:
            self.data[n] = resolved(self.data[n])
            break
          except Exception as e:
            last_exception = e
        else:
          raise TypeError(f"Failed to convert {n} using {tlist}: {last_exception}")

  
  
  def __hash__(self): return hash(str(self).lower())
# endregion


class Environment:
  """Environment class that stores all global data"""
  # data: Dict[str, Any] = {}  # Use class variables with type annotations
  data: ClassVar[Dict[str, Any]] = {}  # Use class variables with type annotations
  initialized: ClassVar[bool] = False
  logger: ClassVar[Logger] = Logger()
  trace_folder: ClassVar[str] = "."
  trace_rules: ClassVar[Dict[str, bool]] = {}  

  @classmethod
  def from_yaml(cls, filename: str) -> 'Environment':
    """Load environment from YAML file"""
    if Environment.initialized:
      return Environment
    
    config = dict_from_yml(filename)
    
    if 'topology' in config:
      config = cls._from_topology(config)
    
    cls.data = config
    cls.initialized = True
    
    if 'trace_folder' in config:
      cls.trace_folder = config['trace_folder']
    
    if 'trace_rules' in config:
      cls.trace_rules = config['trace_rules']
    
    cls.logger = Logger(name="Environment", 
                              level="INFO", 
                              trace_rules=cls.trace_rules,
                              trace_folder=cls.trace_folder)
    

  @classmethod
  def _from_topology(cls, config: dict) -> dict:
    config = dict(config)
    topology = config.pop('topology')
    result = dict_from_yml(topology)
    tunables = config.pop('tunables')
    result.update(tunables)
    result.update(config)
    if 'templates' not in result: result['templates'] = {}
    return result
  

  @classmethod
  def reset(cls) -> None:
    cls.data = {}
    cls.initialized = False
  

  @classmethod
  def get(cls, path: str, default: Any = None) -> Any:
    return deepget(path, cls.data, default)
  
  @classmethod
  def get_int(cls, path: str, default: Optional[int] = None) -> Optional[int]:
    return deepget_int(path, cls.data, default)
  
  @classmethod
  def get_list(cls, path: str, default: Optional[List] = []) -> List:
    return deepget_list(path, cls.data, default)
  
  @classmethod
  def get_dict(cls, path: str, default: Optional[Dict] = {}) -> Dict:
    return deepget_dict(path, cls.data, default)
  