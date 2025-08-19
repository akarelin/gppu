from __future__ import annotations

VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '26'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

import yaml
import re
import logging
import inspect
import pprint
import os.path
from functools import partialmethod
from string import Template
from typing import Any, Dict, List, Union, Optional, Callable, ClassVar
from collections import defaultdict, UserDict, UserList


from pydantic import BaseModel
from rich.console import Console
from rich.theme import Theme
from rich.text import Text


## @@                   Logging                                       
# region Logging
class Logger:
  """
  Core Logger class that implements all logging functionality
  Can be used both globally and injected into classes
  """

  def __init__(self, name: str = "gppu", level: str = "INFO", trace_rules: Optional[Dict[str, bool]] = None, trace_folder: str = "."):
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
  def _msg(*a, level=None, **kw) -> Text:
    """Format args into a string message with optional severity prefix using rich"""
    # Create rich Text object
    result = Text()
    
    # Add severity prefix if provided
    if level:
      if isinstance(level, int): level_str = logging.getLevelName(level)
      else: level_str = str(level)
              
      result.append(f"[{level_str}]", style=SEVERITY_COLORS.get(level_str.lower() if isinstance(level_str, str) else "", ""))
      result.append(" ")
      
    # Add each argument with proper formatting
    for arg in a:
      if isinstance(arg, (list, dict, tuple)):
        # Format complex objects using pprint
        result.append(pprint.pformat(arg, indent=2))
      else:
        # Add simple strings
        result.append(str(arg))
      result.append(" ")
    
    return result  # Return the formatted Text object


  def _log(self, level, *a, **kw):
    # Remove level from kw to avoid duplicate parameter
    if 'level' in kw:
      del kw['level']
    msg = self._msg(*a, level=level, **kw)
    self._logger.log(level, msg)


  def Debug(self, *a, **kw):
    if self._is_debug(self._trace_rules):
      self._logger.debug(self._msg(*a, **kw))
  def Info(self, *a, **kw): self._log(logging.INFO, *a, **kw)
  def Warn(self, *a, **kw): self._log(logging.WARNING, *a, **kw)
  def Error(self, *a, **kw): self._log(logging.ERROR, *a, **kw)
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


_GLOBAL_LOGGER = Logger()
    
Debug: Callable = _GLOBAL_LOGGER.Debug 
Info: Callable = _GLOBAL_LOGGER.Info
Warn: Callable = _GLOBAL_LOGGER.Warn
Error: Callable = _GLOBAL_LOGGER.Error
Fatal: Callable = _GLOBAL_LOGGER.Fatal
# endregion


## $$   Dict utils: deepget, dict_all_paths                           
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


# ##               YAML serializer/deserializer and template engine  
# region YAML serializer/deserializer and template engine
# Custom YAML representer for tuples
def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
  """Custom representer for tuples in YAML"""
  return dumper.represent_dict(dict(enumerate(data)))
# Custom YAML representer for tuples
def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
  """Custom representer for tuples in YAML"""
  return dumper.represent_dict(dict(enumerate(data)))


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

def dict_to_yml(data: Union[Dict[Any, Any], List[Any]], filename: str, config: Optional[YAMLConfig] = None) -> None:
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
  if config is None:
    config = YAMLConfig()

  # Use custom dumper for proper indentation
  class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
      return super().increase_indent(flow, False)
  # Use custom dumper for proper indentation
  class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> yaml.Dumper:
      return super().increase_indent(flow, False)

  # Register custom representers
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, _tuple_representer)
  # Register custom representers
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, _tuple_representer)

  try:
    with open(filename, 'w+') as f:
      yaml.dump(data, f, indent=2, Dumper=IndentedDumper, sort_keys=False, width=2147483647)
  except Exception as err:
    error_msg = f"Error dumping {filename}: {err}"
    with open(f"{filename}_error.txt", 'w+') as ferr:
      ferr.write(error_msg)
    raise RuntimeError(error_msg)
  try:
    with open(filename, 'w+', encoding="utf-8") as f:
      yaml.dump(data, f, indent=2, Dumper=IndentedDumper, sort_keys=False, width=2147483647)
  except Exception as err:
    error_msg = f"Error dumping {filename}: {err}"
    with open(f"{filename}_error.txt", 'w+', encoding='utf-8') as ferr:
      ferr.write(error_msg)
    raise RuntimeError(error_msg)
  try:
    with open(filename, 'w+', encoding="utf-8") as f:
      yaml.dump(data, f, indent=2, Dumper=IndentedDumper, sort_keys=False, width=2147483647)
  except Exception as err:
    error_msg = f"Error dumping {filename}: {err}"
    with open(f"{filename}_error.txt", 'w+', encoding='utf-8') as ferr:
      ferr.write(error_msg)
    raise RuntimeError(error_msg)


def dict_from_yml(filename: str) -> Dict[Any, Any]:
  """
  Load dictionary from YAML file with support for !include directive
  Args:
    data: Dictionary or list to serialize
    filename: Output file path
    config: Optional YAML configuration settings
  """
  if not filename: return
  if config is None:
    config = YAMLConfig()
  # Use custom dumper for proper indentation
  class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> yaml.Dumper:
      return super().increase_indent(flow, False)
  # Register custom representers
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, _tuple_representer)
  try:
    with open(filename, 'w+') as f:
      yaml.dump(data, f, indent=2, Dumper=IndentedDumper, sort_keys=False, width=2147483647)
  except Exception as err:
    error_msg = f"Error dumping {filename}: {err}"
    with open(f"{filename}_error.txt", 'w+') as ferr:
      ferr.write(error_msg)
    raise RuntimeError(error_msg)

def dict_from_yml(filename: str) -> Dict[Any, Any]:
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


# --                              y2list, y2eid, y2path, y2slug, y2topic   
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


# __                              Environment                                     
# region Environment
class Environment:
  """Environment class that stores all global data"""
  # data: Dict[str, Any] = {}  # Use class variables with type annotations
  data: ClassVar[Dict[str, Any]] = {}  # Use class variables with type annotations
  initialized: ClassVar[bool] = False
  logger: ClassVar[Logger] = Logger()
  trace_folder: ClassVar[str] = "."
  trace_rules: ClassVar[Dict[str, bool]] = {}  

  @classmethod
  def from_yaml(cls, filename: str) -> None:
    """Load environment from YAML file"""
    if Environment.initialized: return
    
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
# endregion


# &&                              Colors                                          
# region Colors
# Create rich theme that maps to the old TColor styles
rich_theme = Theme({
  "none": "",
  "dim": "dim",
  "bright": "bold cyan",  # 36;1
  "bw": "bold white",     # 38;5;15;1
  "dw": "white",          # 38;5;7;1
  
  # Grays
  "gray1": "rgb(45,45,45)",    # 38;5;237
  "gray2": "rgb(60,60,60)",    # 38;5;239/243
  "gray3": "rgb(100,100,100)", # 38;5;246
  "gray4": "rgb(140,140,140)", # 38;5;249
  
  # Colors
  "by": "bold yellow",    # 38;5;11;1
  "dy": "yellow",         # 38;5;3;1
  "bg": "bold green",     # 38;5;10;1
  "dg": "green",          # 38;5;2;1
  "db": "blue",           # 38;5;4;1
  "bc": "bold cyan",      # 38;5;6;1
  "dc": "cyan",           # 38;5;14;1
  "bm": "bold magenta",   # 38;5;13;1
  "dm": "magenta",        # 38;5;5;1
  "br": "bold red",       # 38;5;9;1
  "dr": "red",            # 38;5;1;1
  "bp": "bold rgb(135,0,175)",  # 38;5;129;1
  "dp": "rgb(90,0,135)",        # 38;5;90;1
  "bo": "bold rgb(175,95,0)",   # 38;5;130;1
  "do": "rgb(175,95,0)",        # 38;5;130;1
  "pink": "bold rgb(255,0,175)",  # 38;5;200;1
  "dpink": "rgb(175,95,135)",     # 38;5;132;1
  "bgold": "bold rgb(255,175,0)",  # 38;5;220;1
  "dgold": "rgb(215,135,0)",       # 38;5;178;1
  
  # Special styles
  "info": "bold blue",          # 34;1
  "white": "black on white",    # 0;30;47
  "yellow": "black on yellow",  # 0;30;43
  "red": "black on red",        # 0;30;41
  "blue": "black on blue",      # 0;30;44
  "green": "black on green",    # 0;30;42
  "wred": "white on red",       # 0;37;41
  "wblue": "white on blue",     # 0;37;44
  "wgreen": "white on green",   # 0;37;42
  "wgray": "black on white",    # 0;30;47
  "wpink": "black on magenta",  # 0;30;45
  "wpurple": "white on purple", # 0;37;45
  "wyellow": "reverse yellow",  # 7;49;93
})

console = Console(theme=rich_theme)

class _TColorHack(type):
  def __getitem__(cls, key): return getattr(cls, str(key), None)
  def __contains__(cls, key): return hasattr(cls, str(key))

  def print(cls):
    for name in dir(cls):
      if not name.startswith('_') and isinstance(getattr(cls, name), str):
        console.print(f"[{name}]{name}[/]", end=" ")
    console.print()

class TColor(metaclass=_TColorHack):
  NONE = "none"
  DIM = "dim"
  BRIGHT = "bright"
  BW = "bw"
  DW = "dw"
  
  GRAY1 = "gray1"
  GRAY2 = "gray2"
  GRAY3 = "gray3"
  GRAY4 = "gray4"
  
  BY = "by"
  DY = "dy"
  BG = "bg"
  DG = "dg"
  DB = "db"
  BC = "bc"
  DC = "dc"
  BM = "bm"
  DM = "dm"
  BR = "br"
  DR = "dr"
  BP = "bp"
  DP = "dp"
  BO = "bo"
  DO = "do"
  PINK = "pink"
  DPINK = "dpink"
  BGOLD = "bgold"
  DGOLD = "dgold"
  
  ORANGE = BO
  PURPLE = BP
  
  INFO = "info"
  WHITE = "white"
  YELLOW = "yellow"
  RED = "red"
  BLUE = "blue"
  GREEN = "green"
  
  WRED = "wred"
  WBLUE = "wblue"
  WGREEN = "wgreen"
  WGRAY = "wgray"
  WPINK = "wpink"
  WPURPLE = "wpurple"
  WYELLOW = "wyellow"

COLORS = {k: v for k, v in TColor.__dict__.items() 
          if not k.startswith('_') and isinstance(v, str)}

def _colorize_list(items: List) -> Text:
  """Colorizes list of strings using rich Text"""
  result = Text()
  current_style = None

  for i, item in enumerate(items):
    if not item:
      continue
      
    # Check if this item is a color/style name
    item_str = str(item)
    if item_str in COLORS:
      current_style = item_str
      continue
      
    # Handle special prefixes like ./ that don't need spaces
    needs_space = True
    if item_str.startswith(".") or item_str.startswith("/"):
      needs_space = False
      item_str = item_str[1:]
      
    # Add a space if needed and not the first item
    if i > 0 and needs_space and result.plain:
      result.append(" ")
      
    # Add the text with current style
    if current_style:
      result.append(item_str, style=current_style)
    else:
      result.append(item_str)
      
  return result

def pcp(*a: Union[str, List[Any], tuple], **kw: Any) -> str:
  """
  Pretty colored print using rich. Supports two kinds of input:
    level, msg: compatible with default logger
    [args]: used to colorize output
  Returns: colored string
  
  Parameters:
    verbose: adds pfy(kwargs) to output
    silent: suppresses local print output
  """
  if len(a) == 1 and isinstance(a[0], tuple):
    a = tuple(a[0])
  
  out = ""
  verbose = kw.pop('verbose', False)
  silent = kw.pop('silent', False)
  level = kw.pop('level', None)
  
  # Create a rich Text object to build our output
  result = Text()
  
  if 'msg' in kw:
    msg = kw.get('msg')
    if isinstance(msg, tuple):
      result = _colorize_list(list(msg))
    elif level:
      if level in ['CRITICAL', 'ERROR']:
        c1, c2 = 'br', 'bright'
      elif level in ['WARN', 'WARNING']:
        c1, c2 = 'by', 'bright'
      elif level in ['INFO']:
        c1, c2 = 'blue', 'info'
      elif level in ['DEBUG']:
        c1, c2 = 'dim', 'dim'
      else:
        c1, c2 = 'dim', 'info'
      
      level_text = Text(level, style=c1)
      msg_text = Text(f" {msg}", style=c2)
      result.append(level_text)
      result.append(msg_text)
    else:
      result.append(Text(str(msg)))
    
    if a:
      list_text = _colorize_list(list(a))
      result.append(list_text)
  else:
    result = _colorize_list(list(a))
  
  if kw and verbose:
    result.append(Text("\n" + pprint.pformat(kw, indent=4, width=40, compact=True)))
  
  # Print if not silent
  if not silent:
    console.print(result)
  
  # Return plain text representation for compatibility
  return result.plain

SHORTEN_BY_PREFIX = ['process_', '_cb_']
IGNORE_FUNCTIONS = ['dpcp', 'trace', 'pcp', 'Trace']
SEVERITY_COLORS = {
  'Error': 'wred', 
  'Warn': 'wyellow', 
  'Info': 'wblue', 
  'Debug': 'gray4', 
  None: 'wpurple'
}

def dpcp(*a: Any, conditional: Optional[bool] = None, rules: Dict[str, bool] = {},
       no_prefix: bool = False, severity: Optional[str] = None, **kw: Any) -> Optional[str]:
  """Version of pcp that adds info on where it was called from"""
  remove_prefixes = lambda s, prefixes: next((s.removeprefix(prefix) for prefix in prefixes if s.startswith(prefix)), s)

  def is_traced(name: Optional[str] = None) -> bool:
    if not conditional:
      return True
    if not name or name not in rules:
      return rules.get('all', False)
    else:
      return rules.get(name, False)

  if not conditional and rules:
    conditional = True
  
  frame = inspect.currentframe()
  if frame is None:
    return None

  frame = frame.f_back
  while frame and frame.f_back:
    frame = frame.f_back
    frame_info = inspect.getframeinfo(frame)
    filename = frame_info.filename
    func_name = frame_info.function

    if func_name not in IGNORE_FUNCTIONS:
      break
    func_name = remove_prefixes(func_name, SHORTEN_BY_PREFIX)

  if frame is None:
    return None

  if not is_traced(func_name):
    return None
  
  module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
  if not is_traced(module) or not is_traced(f"{module}.{func_name}"):
    return None

  args_list = []
  
  if 'self' in frame.f_locals:
    class_name = frame.f_locals["self"].__class__.__name__
    if not is_traced(class_name):
      return None
    if not is_traced(f"{class_name}.{func_name}"):
      return None
    
    if not no_prefix:
      args_list.extend(['gray1', f"{class_name}.", 'gray2', f".{func_name}"])
  else:
    if not no_prefix:
      args_list.extend(['gray2', f".{func_name}"])

  if severity and not no_prefix:
    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS[None])
    args_list = [color, severity] + args_list

  if no_prefix:
    args_list = list(a)
  else:
    args_list.extend(list(a))

  return pcp(*args_list, **kw)
# endregion