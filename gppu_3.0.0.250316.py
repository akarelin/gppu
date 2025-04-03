import sys

VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '250316'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

import yaml
import logging
import inspect
import pprint
from functools import partialmethod

from pydantic import BaseModel
from typing import Any, Dict, List, Union, Optional
from collections import defaultdict, UserDict, UserList
import os.path
import sys
from typing import Any, Dict, List, Union, Optional, Callable, TypeVar, cast
import yaml
import logging
import inspect
import pprint
from functools import partialmethod
from pydantic import BaseModel
from collections import defaultdict, UserDict, UserList
import os.path
import sys
from typing import Any, Dict, List, Union, Optional, Callable, TypeVar, cast
import yaml
import logging
import inspect
import pprint
from functools import partialmethod
from pydantic import BaseModel
from collections import defaultdict, UserDict, UserList
import os.path

VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '250316'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"
VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '250316'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"


def format_args(*a, severity=None, **kw):
  """Format args into a string message with optional severity prefix"""
  parts = []

  if severity: parts.append(f"[{severity}]")
def format_args(*a: Any, severity: Optional[str] = None, **kw: Any) -> str:
  """Format args into a string message with optional severity prefix"""
  parts: List[str] = []
  if severity: parts.append(f"[{severity}]")
def format_args(*a: Any, severity: Optional[str] = None, **kw: Any) -> str:
  """Format args into a string message with optional severity prefix"""
  parts: List[str] = []
  if severity: parts.append(f"[{severity}]")

  for arg in a:
    if isinstance(arg, (list, dict, tuple)): parts.append(pprint.pformat(arg, indent=2))
    else: parts.append(str(arg))
  for k, w in kw.items():
    parts.append(f"{k}={w}")
  for arg in a:
    if isinstance(arg, (list, dict, tuple)): parts.append(pprint.pformat(arg, indent=2))
    else: parts.append(str(arg))
  for k, w in kw.items():
    parts.append(f"{k}={w}")

  return " ".join(parts)
  return " ".join(parts)


class Logger:
  """
  Core Logger class that implements all logging functionality
  Can be used both globally and injected into classes
  """
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
  def __init__(self, name: str = "gppu", level: str = "INFO", trace_rules: Optional[Dict[str, bool]] = None, trace_folder: str = "."):
    self.name = name
    self._logger = logging.getLogger(name)
    self._trace_rules = trace_rules or {}
    self._trace_folder = trace_folder

    self._logger.setLevel(getattr(logging, level))
    self._logger.setLevel(getattr(logging, level))

  @staticmethod
  def _should_trace(rules: Dict[str, bool]) -> bool:
    if not rules: return True
  @staticmethod
  def _should_trace(rules: Dict[str, bool]) -> bool:
    if not rules: return True

    frame = inspect.currentframe()
    if frame is None: return False
    frame = inspect.currentframe()
    if frame is None: return False

    frame = frame.f_back
    if frame is None: return False
    frame = frame.f_back
    if frame is None: return False

    frame_info = inspect.getframeinfo(frame)
    func_name = frame_info.function
    filename = frame_info.filename
    module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
    frame_info = inspect.getframeinfo(frame)
    func_name = frame_info.function
    filename = frame_info.filename
    module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]

    if rules.get(func_name, False): return True
    if rules.get(module, False): return True
    if rules.get(func_name, False): return True
    if rules.get(module, False): return True

    if 'self' in frame.f_locals:
      class_name = frame.f_locals["self"].__class__.__name__
      if rules.get(f"{class_name}.{func_name}", False): return True
      if rules.get(class_name, False): return True
    if 'self' in frame.f_locals:
      class_name = frame.f_locals["self"].__class__.__name__
      if rules.get(f"{class_name}.{func_name}", False): return True
      if rules.get(class_name, False): return True

    return rules.get('all', False)
    return rules.get('all', False)

  def _log(self, level, *a, **kw):
    msg = format_args(*a, level=level, **kw)
    self._logger.log(level, msg)
  def _log(self, level: int, *a: Any, **kw: Any) -> None:
    msg = format_args(*a, **kw)
    self._logger.log(level, msg)
  for arg in a:
    if isinstance(arg, (list, dict, tuple)): parts.append(pprint.pformat(arg, indent=2))
    else: parts.append(str(arg))
  for k, w in kw.items():
    parts.append(f"{k}={w}")
  return " ".join(parts)
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
  def _should_trace(rules: Dict[str, bool]) -> bool:
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
  def _log(self, level: int, *a: Any, **kw: Any) -> None:
    msg = format_args(*a, **kw)
    self._logger.log(level, msg)

  def Trace(self, *a, **kw):
    if self._should_trace(self._trace_rules):
      self._logger.debug(format_args(*a, **kw))
  def Trace(self, *a: Any, **kw: Any) -> None:
    if self._should_trace(self._trace_rules):
      self._logger.debug(format_args(*a, **kw))

  Info = partialmethod(_log, level=logging.INFO)
  Debug = partialmethod(_log, level=logging.DEBUG)
  Warning = partialmethod(_log, level=logging.WARNING)
  Error = partialmethod(_log, level=logging.ERROR)

  # def Dump(self, data, filename: str):
  #   """Dump data to YAML file"""
  #   if '.' not in filename or not filename.endswith('.yml'):
  #     filename += '.yml'
  #   if '/' not in filename:
  #     filename = self._trace_folder + '/' + filename
  #
  #   # Use the existing dict_to_yml function
  #   dict_to_yml(filename=filename, data=data)
  # Use proper type annotations for partialmethod
  Info: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.INFO))
  Debug: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.DEBUG))
  Warning: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.WARNING))
  Error: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.ERROR))
  def Trace(self, *a: Any, **kw: Any) -> None:
    if self._should_trace(self._trace_rules):
      self._logger.debug(format_args(*a, **kw))
  # Use proper type annotations for partialmethod
  Info: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.INFO))
  Debug: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.DEBUG))
  Warning: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.WARNING))
  Error: Callable[..., None] = cast(Callable[..., None], partialmethod(_log, level=logging.ERROR))

  # def Dump(self, data: Any, filename: str) -> None:
  #   """Dump data to YAML file"""
  #   if '.' not in filename or not filename.endswith('.yml'):
  #     filename += '.yml'
  #   if '/' not in filename:
  #     filename = self._trace_folder + '/' + filename
  #
  #   # Use the existing dict_to_yml function
  # def Dump(self, data: Any, filename: str) -> None:
  #   """Dump data to YAML file"""
  #   if '.' not in filename or not filename.endswith('.yml'):
  #     filename += '.yml'
  #   if '/' not in filename:
  #     filename = self._trace_folder + '/' + filename
  #
  #   # Use the existing dict_to_yml function
  #   dict_to_yml(filename=filename, data=data)
  #   dict_to_yml(filename=filename, data=data)


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
class YAMLConfig(BaseModel):
  keys_first: List[str] = ["name", "path"]
  keys_drop: List[str] = ["api", "adapi", "AD"]
  keys_force_string: List[str] = ["parent"]

class Config:
  arbitrary_types_allowed = True
  class Config:
    arbitrary_types_allowed = True


# Custom YAML representer for tuples
def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
  """Custom representer for tuples in YAML"""
  return dumper.represent_dict(dict(enumerate(data)))
# Custom YAML representer for tuples
def _tuple_representer(dumper: yaml.Dumper, data: tuple) -> yaml.nodes.Node:
  """Custom representer for tuples in YAML"""
  return dumper.represent_dict(dict(enumerate(data)))


def dict_to_yml(data: Union[Dict, List], filename: str, config: Optional[YAMLConfig] = None) -> None:
  """
  Save dictionary to YAML file with proper indentation and ordering
T = TypeVar('T', Dict[Any, Any], List[Any])
def dict_to_yml(data: Union[Dict[Any, Any], List[Any]], filename: str, config: Optional[YAMLConfig] = None) -> None:
  """
  Save dictionary to YAML file with proper indentation and ordering
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
T = TypeVar('T', Dict[Any, Any], List[Any])
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
def dict_from_yml(filename: str) -> Dict[Any, Any]:
  """
  Load dictionary from YAML file with support for !include directive
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
  Args:
    filename: Path to YAML file

  Returns:
    Dictionary loaded from YAML
  """
  if not os.path.exists(filename):
    raise FileNotFoundError(f"YAML file not found: {filename}")
  Returns:
    Dictionary loaded from YAML
  """
  if not os.path.exists(filename):
    raise FileNotFoundError(f"YAML file not found: {filename}")

  yml_root = os.path.dirname(filename)
  yml_root = os.path.dirname(filename)

  # Custom constructor for handling !include directive
  def yml_include(loader, node):
    include_path = node.value
    if not include_path.startswith('/'):
      include_path = os.path.join(yml_root, include_path)
  # Custom constructor for handling !include directive
  def yml_include(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    include_path = str(node.value)
    if not include_path.startswith('/'):
      include_path = os.path.join(yml_root, include_path)
  Args:
    filename: Path to YAML file
  Returns:
    Dictionary loaded from YAML
  """
  if not os.path.exists(filename):
    raise FileNotFoundError(f"YAML file not found: {filename}")
  yml_root = os.path.dirname(filename)
  # Custom constructor for handling !include directive
  def yml_include(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    include_path = str(node.value)
    if not include_path.startswith('/'):
      include_path = os.path.join(yml_root, include_path)

    with open(include_path, "r") as f:
      return yaml.safe_load(f)
  # Register custom constructors
  yaml.add_constructor("!include", yml_include, Loader=yaml.SafeLoader)
  with open(filename, "r") as f:
    return yaml.safe_load(f) or {}
