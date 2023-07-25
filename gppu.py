# General purpose python utilities
import pprint
import yaml
import re
from glob import glob

from string import Template

from collections import defaultdict, UserList, UserDict
#from collections.abc import Mapping, Sequence
from datetime import datetime

"""Safe typecasting"""
def safe_list(o) -> list:
  result = []
  if isinstance(o, str): result = [o]
  elif isinstance(o, list): result = [element for element in o if element]
  elif isinstance(o, dict): result = list(o.keys())
  return result
def safe_int(o, default=0) -> int:
  v = safe_float(o, default)
  if v: return int(v)
  else: return default
def safe_float(o, default=-1.0) -> float:
  if o is None: return default
  if isinstance(o, str):
    o = o.removesuffix("°c")
    o = o.removesuffix("%")
  try: v = float(o)
  except: v = default
  return v

"""Deep, dict and yaml utils"""
deepdict = lambda: defaultdict(deepdict)
def deepget(path: str, d: dict, default=None):
  if '/' in path and path not in d.keys():
    _ = dict(d)
    for pp in path.split('/'):
      _ = _.get(pp)
      if not _: break
    return _ if _ else default
  return d.get(path, default)

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

# def safe_add_unique(d: dict, key: str, value):
#   """ To be used with dicts of lists. Function adds another element to the list stored in dict with key. """
#   try: _ = set(d[key])
#   except: _ = set()
#   if isinstance(_, str): result = set([_, value])
#   elif isinstance(_, (set, list)): result = _.add(value)
#   else: raise TypeError(f"Unsafe unique: {type(_)}")
#   d[key] = result

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

def islist(o): return isinstance(o, (list, set))
def isdict(o): return isinstance(o, (dict, defaultdict, UserDict))
def isscalar(o): 
  
  return isinstance(o, (float, int, str))

def dict_sanitize(data, as_is=True):
  """Convert nested complex data types for json.dumps or yaml.dumps"""
  def sanitize_list(o) -> list:
    result = []
    if hasattr(o, 'data'): l = list(o.data)
    else: l = list(o)
    for e in list(l):
      if isdict(e): _ = sanitize_dict(e)
      elif islist(e): _ = sanitize_list(e)
      else: _ = str(e) if e else None
      if as_is or _: result.append(_)
    return result

  def sanitize_dict(o) -> dict:
    result = {}
    if hasattr(o, 'data'): d = dict(o.data)
    else: d = dict(o)
    for k, v in [(str(k), v) for k, v in dict(d).items() if as_is or v]:
      if isdict(v): _ = sanitize_dict(v)
      elif islist(v): _ = sanitize_list(v)
      elif isscalar(v): _ = v
      else: _ = str(v) if v else None
      if as_is or _: result[k] = _
    return result

  if isdict(data): return sanitize_dict(data)
  elif islist(data): return sanitize_list(data)
  else: raise ValueError(f"Unable to sanitize {data}")

def dict_as_yaml(data={}):
  redata = dict_sanitize(data)

  #if timestampit: filename = timestamp() + " " + filename
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, yaml.representer.Representer.represent_dict)
  try:
    result = yaml.dump(redata)
  except Exception as err:
    raise RuntimeError(f"Error {err} in dict_as_yaml\n {type(err)}\n{pfy(redata)}\n\n")
    #error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
    #with open(filename+'_error.txt','w+') as ferr: ferr.write(error)
  return result

def dict_to_yml(filename:str, data=None, as_is=True):
  assert filename
  if not data: return

  redata = dict_sanitize(data)

  #if timestampit: filename = timestamp() + " " + filename
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, yaml.representer.Representer.represent_dict)
  with open(filename,'w+') as f: 
    try: yaml.dump(redata, f)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
      with open(filename+'_error.txt','w+') as ferr: ferr.write(error)
     
def dict_from_yml(filename:str):
  result = {}
  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, yaml.representer.Representer.represent_dict)

  with open(filename) as f: return dict(yaml.load(f, Loader=yaml.FullLoader))

def dict_from_yml_directory(folder:str, prefix:str) -> dict:
  """ Loads all yaml files from folder that start with prefix
      merges all dicts from files using prefix as key
  """
  result = {}
  pathname = f"{folder}/{prefix}_*.yaml"
  for fname in glob(pathname):
    key = fname.removeprefix(folder).removesuffix('.yaml').split('_')[1]
    result[key] = dict_from_yml(fname)
  return result

def dict_from_yaml_list(yaml_list, default=None) -> dict:
  """
  Convert YAML list like in the example to dict:

    - binary_sensor.cellar_sensor@kaksi:
        area: ['cellar']
        purpose: ['occupancy','motion']
        timeout: 180
  """
  if isinstance(yaml_list, dict): return yaml_list
  assert isinstance(yaml_list, list)
  result = {}
  #_ = {(list(element.keys()))[0]: dict(list(element.values())[0]) for element in yaml_list}
  for element in yaml_list:
    if isinstance(element, str): result[element] = None
    elif isinstance(element, dict):
      for key, value in element.items():
        if key not in result: result[key] = value
        elif isinstance(value, dict): result[key].update(value)
        elif isinstance(value, list): result[key].append(value)
  return result if result else default

def template_populate(template, data):
  if not template: result = None
  elif isinstance(template, dict):
    result = {}
    for k, old in template.items():
      new = template_populate(old, data)
      result[k] = new
  elif isinstance(template, list):
    result = []
    for old in template:
      new = template_populate(old, data)
      result.append(new)
  elif isinstance(template, (int, bool, float)): result = template
  else: result = Template(str(template)).safe_substitute(data)
  return result


"""Logging"""
def now_str(): return datetime.now().strftime("%Y%m%d.%H%M%S")
def now_ts(): return datetime.now().timestamp()
def pretty_timedelta(ts):
  now = datetime.now().timestamp()
  delta = now - ts
  seconds = int(delta)
  days, seconds = divmod(seconds, 86400)
  hours, seconds = divmod(seconds, 3600)
  minutes, seconds = divmod(seconds, 60)
  if days > 0:
    return '%dd %dh %dm %ds' % (days, hours, minutes, seconds)
  elif hours > 0:
    return '%dh %dm %ds' % (hours, minutes, seconds)
  elif minutes > 0:
    return '%dm %ds' % (minutes, seconds)
  else:
    return '%ds' % (seconds,)
    
def pfy(object) -> str: return "\n"+pprint.pformat(object, indent=4, width=40, compact=True)
def slugify(o) -> str:
  """Converts any object to string, then slugifies it"""
  return re.sub(r'[^a-zA-Z0-9_]', '_', str(o).lower())

# def dargs(*args): print(log_colored(args))

def _print_terminal_color_table():
  for b in "34":
    s = ""
    for f in "01234567": s += colorpad(f+b+';1', f"{f+b+';1'}") + "  "
    print(s)

  for f in range(0, 15):
    s = colorpad(f"38;5;{f};1", f"38;5;{f};1")+"  "
    print(s)

  for b in range(0, 1):
    s = ""
    for f in range(0, 15): s += colorpad(f"38;5;{f};1", f"38;5;{f};1")+"  "
    print(s)

TERMINAL_COLORS = {
    'NONE':   '0m',
    'DIM':    '38;5;8;1',
    'BRIGHT': '36;1',
    'BW':     '38;5;7;1',
    'BY':     '38;5;11;1',
    'BG':     '38;5;10;1',
    'INFO':   '34;1',
    'WHITE':  '0;30;47',
    'YELLOW': '0;30;43',
    'RED':    '0;30;41',
    'BLUE':   '0;30;44',
    'GREEN':  '0;30;42'
}

def pcp(*args, **kwargs) -> str:
  """
  Pretty colored print. Supports two kinds of input:
    level, msg: compatible with default logger
    [args]: used by self.Dargs to colorize output
  Returns: colored string
  
  Parameters:
    verbose: adds pfy(kwargs) to output
    silent: suppresses local print output
    
  """
  if len(args) == 1 and isinstance(args[0], tuple): args = list(args[0])
  out = ""
  verbose = kwargs.pop('verbose', False)
  silent = kwargs.pop('silent', False)
  if 'level' in kwargs:
    level = kwargs.pop('level')
    msg = kwargs.pop('msg')
    out = colorize_log(msg=msg, level=level)
    if args: out += colorize_list(args)
  else:
    out = colorize_list(args)
  if kwargs and verbose: out += pfy(kwargs)
  if not silent: print(out)
  return out

def colorize_log(msg, level=None, *args):
  if isinstance(msg, tuple): msg = colorize_list(msg)
  elif level:
    if level in ['CRITICAL', 'ERROR']: color = 'RED'
    elif level in ['WARN']: color = 'YELLOW'
    elif level in ['INFO']: color = 'BLUE'
    elif level in ['DEBUG']: color = 'DIM'
    else: color = 'NONE'
    msg = colorize(color, level) + ' ' + msg
  #else: raise ValueError(f"Invalid log_colored call: {msg} {level} {args}")
  return msg

def colorize_list(l: list):
  result = []
  color = None
  for e in l:
    if str(e) in TERMINAL_COLORS: color = e
    elif color: result.append(colorize(color, str(e)))
    else: result.append(str(e))
  return ' '.join(result)

def colorize(color:str, text:str, fmt=None):
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
  if color in TERMINAL_COLORS: color = TERMINAL_COLORS[color]
  ESC = '\u001b'
  NOP = ESC + '[0m'
  if color:
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
    maxlen = safe_int(fmt, 0)

    text = text[-maxlen:] if right else text[0:maxlen]
    if (l := len(text)) < maxlen: pad = ' ' * (maxlen - l)

  text = color + text + NOP
  return pad + text if right else text + pad
