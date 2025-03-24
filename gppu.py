from __future__ import annotations

VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '23'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

import yaml
import logging
import inspect
import pprint
from functools import partialmethod

from pydantic import BaseModel
from typing import Any, Dict, List, Union, Optional, Callable, ClassVar
from collections import defaultdict, UserDict
import os.path


class Logger:
  """
  Core Logger class that implements all logging functionality
  Can be used both globally and injected into classes
  """

  def __init__(self, name: str = "gppu", level: str = "INFO",trace_rules: Dict[str, bool] = None, trace_folder: str = "."):
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
    msg = self._msg(*a, level=level, **kw)
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


from pydantic import BaseModel, Field, model_validator
from typing import Dict, Any

class YData(BaseModel, UserDict):
  """Dictionary with Pydantic validation and deep access methods"""
  
  # UserDict needs a 'data' attribute
  data: Dict[str, Any] = Field(default_factory=dict)
  
  model_config = {
    "arbitrary_types_allowed": True,
    "extra": "allow"
  }
  
  def __init__(self, *args, **kwargs):
    # Initialize both parent classes
    BaseModel.__init__(self, **kwargs)
    UserDict.__init__(self, self.data)
  
  def get(self, path: str, default: Any = None) -> Any:
    """Returns value at path, or default if not found"""
    return deepget(path, self.data, default)
  
  def get_int(self, path: str, default: Optional[int] = None) -> Optional[int]:
    """Returns int at path, or default if not found"""
    return deepget_int(path, self.data, default)
  
  def get_list(self, path: str, default: Optional[List] = None) -> List:
    """Returns list at path, or default if not found"""
    if default is None:
      default = []
    return deepget_list(path, self.data, default)
  
  def get_dict(self, path: str, default: Optional[Dict] = None) -> Dict:
    """Returns dict at path, or default if not found"""
    if default is None:
      default = {}
    return deepget_dict(path, self.data, default)
  
  def model_dump(self, *args, **kwargs):
    """Return the model as a dictionary"""
    # Start with the standard model dump
    result = super().model_dump(*args, **kwargs)
    # Add any keys from UserDict not already in the model_dump
    for k, v in self.data.items():
      if k not in result:
        result[k] = v
    return result


class Environment(YData):
  """Environment class that stores all global data"""
  data: Dict[str, Any] = {}  # Use class variables with type annotations
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
  