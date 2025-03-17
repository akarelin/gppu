VER_GPPU_BASE = '3.0.0'
VER_GPPU_BUILD = '250316'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

import yaml
from pydantic import BaseModel
from typing import Any, Dict, List, Union, Optional
from collections import defaultdict, UserDict, UserList
import os.path


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
