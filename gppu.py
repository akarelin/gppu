import sys
from __future__ import annotations

VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '18'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

import yaml
import logging
import inspect
import pprint
from functools import partialmethod

from pydantic import BaseModel
from typing import Any, Dict, List, Union, Optional, Callable
from collections import defaultdict, UserDict, DefaultDict
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

Debug: Callable = Logger.Debug 
Info: Callable = Logger.Info
Warn: Callable = Logger.Warn
Error: Callable = Logger.Error
Fatal: Callable = Logger.Fatal

# Dump: Callable = Logger.Dump

  # def Dump(self, data, filename: str):
  #   """Dump data to YAML file"""
  #   if '.' not in filename or not filename.endswith('.yml'):
  #     filename += '.yml'
  #   if '/' not in filename:
  #     filename = self._trace_folder + '/' + filename
  #
  #   # Use the existing dict_to_yml function
  #   dict_to_yml(filename=filename, data=data)


# region Dict utils: deepget, dict_all_paths
# DeepDict = DefaultDict[str, "DeepDict"]
# deepdict: Callable[[], DeepDict] = lambda: defaultdict(deepdict)
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
    with open(filename, 'w+') as f:
      yaml.dump(data, f, indent=2, Dumper=IndentedDumper, sort_keys=False, width=2147483647)
  except Exception as err:
    error_msg = f"Error dumping {filename}: {err}"
    with open(f"{filename}_error.txt", 'w+') as ferr:
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

    with open(include_path, "r") as f:
      return yaml.safe_load(f)

  # Register custom constructors
  yaml.add_constructor("!include", yml_include, Loader=yaml.SafeLoader)

  with open(filename, "r") as f:
    return yaml.safe_load(f) or {}



from pydantic import BaseModel, Field, model_validator
from typing import Dict, Any


class PydanticYData(BaseModel):
  """Dict-based YData implemented with Pydantic"""
  __data: Dict[str, Any] = Field(default_factory=dict, alias="data")
  
  model_config = {
    "arbitrary_types_allowed": True,
    "extra": "allow"
  }
  
  @model_validator(mode='before')
  @classmethod
  def process_data(cls, data):
    if isinstance(data, dict):
      data_dict = data.get('data', {})
      if isinstance(data_dict, dict):
        for k, v in data_dict.items():
          if k not in data:
            data[k] = v
    return data
  

  def __getitem__(self, key):
    if hasattr(self, "model_fields_set") and key in self.model_fields_set:
      return getattr(self, key)
    if key in self.__data:
      return self.__data[key]
    raise KeyError(key)
  

  def __setitem__(self, key, value):
    if hasattr(self.__class__, key) and isinstance(getattr(self.__class__, key), property):
      setattr(self, key, value)
    elif hasattr(self, "model_fields") and key in self.model_fields:
      setattr(self, key, value)
    else:
      self.__data[key] = value
  

  def get(self, path: str, default: Any = None) -> Any:
    """Returns value at path, or default if not found"""
    return deepget(path, self.model_dump(), default)
  
  def get_int(self, path: str, default: Optional[int] = None) -> Optional[int]:
    """Returns int at path, or default if not found"""
    return deepget_int(path, self.model_dump(), default)
  
  def get_list(self, path: str, default: list = []) -> list:
    """Returns list at path, or default if not found"""
    return deepget_list(path, self.model_dump(), default)
  
  def get_dict(self, path: str, default: dict = {}) -> dict:
    """Returns dict at path, or default if not found"""
    return deepget_dict(path, self.model_dump(), default)
  
  def items(self):
    result = dict(self.__data)
    if hasattr(self, "model_fields_set"):
      for k in self.model_fields_set:
        if k != 'data':
          result[k] = getattr(self, k)
    return result.items()
  

  def keys(self): return dict(self.items()).keys()
  def values(self): return dict(self.items()).values()
  

  def __contains__(self, key): 
    return (hasattr(self, "model_fields_set") and key in self.model_fields_set) or key in self.__data
  

  def model_dump(self, *args, **kwargs):
    result = super().model_dump(*args, **kwargs)
    if 'data' in result:
      for k, v in result['data'].items():
        result[k] = v
      del result['data']
    return result
    

  def __hash__(self): 
    return hash(str(self).lower())
  

class Environment(PydanticYData):
  """Environment class that stores all global data"""
  data: Dict[str, Any] = {}
  initialized: bool = False
  logger: Logger = Logger()
  trace_folder: str = "."
  trace_rules: Dict[str, bool] = {}
  TRACE_RULES = trace_rules
  

  @staticmethod
  def from_yaml(filename: str) -> 'Environment':
    """Load environment from YAML file"""
    if Environment.initialized:
      return Environment
    
    config = dict_from_yml(filename)
    
    if 'topology' in config:
      config = Environment._from_topology(config)
    
    Environment.data = config
    Environment.initialized = True
    
    if 'trace_folder' in config:
      Environment.trace_folder = config['trace_folder']
    
    if 'trace_rules' in config:
      Environment.trace_rules = config['trace_rules']
      Environment.TRACE_RULES = config['trace_rules']
    
    Environment.logger = Logger(name="Environment", 
                              level="INFO", 
                              trace_rules=Environment.trace_rules,
                              trace_folder=Environment.trace_folder)
    
    return Environment


  @staticmethod
  def _from_topology(config: dict) -> dict:
    config = dict(config)
    topology = config.pop('topology')
    result = dict_from_yml(topology)
    tunables = config.pop('tunables')
    result.update(tunables)
    result.update(config)
    if 'templates' not in result: result['templates'] = {}
    return result
  

  @staticmethod
  def reset() -> None:
    Environment.data = {}
    Environment.initialized = False
  

  @staticmethod
  def glob(path, default=None) -> Any:
    return deepget(path, Environment.data, default=default)
  

  @staticmethod
  def glob_int(path, default=None) -> Any:
    return deepget_int(path, Environment.data, default=default)
  

  @staticmethod
  def glob_list(path, default=None) -> Any:
    if default is None:
      default = []
    return deepget_list(path, Environment.data, default=default)
  

  @staticmethod
  def glob_dict(path, default=None) -> Any:
    if default is None:
      default = {}
    return deepget_dict(path, Environment.data, default=default)
  

  @staticmethod
  def dump():
    Logger.Dump('Environment.data', Environment.data)
  