from functools import partial
import pprint
import yaml
import re
import inspect
from glob import glob

from typing import TypeVar, Union, get_origin, get_args, Callable, Any

from string import Template
from copy import copy, deepcopy

from collections import defaultdict, UserDict
from datetime import datetime

VER_GPPU_BASE = '2.4.6'
VER_GPPU_BUILD = '230914'
VER_GPPU = f"{VER_GPPU_BASE}.{VER_GPPU_BUILD}"

# region Safe typecasting
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
def safe_isinstance(o: object, typ: type, default: bool = False) -> bool:
  """ Safe version of isinstance. Use with default=True to be more permissive """
  if typ in {Any}: return True
  problematic = {Union, TypeVar}
  safe = {int, float, str, dict, list}
  if typ in problematic: return default 
  if set(get_args(typ)) - safe: return default # ! Unsafe type detected
  if get_origin(typ) in problematic: return default
  return isinstance(o, typ)
# endregion

# region Dict utils: deepget, dict_all_paths
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
KEYS_FORCE_STRING = ['parent']
KEYS_DROP = ['api', 'adapi']
KEYS_FIRST = ['name', 'path']

def isstring(o) -> bool:
  relatives = {type(o).__qualname__}
  relatives |= {c.__qualname__ for c in o.__class__.__mro__}
  return bool({'y2list', 'str', 'y2topic', 'y2path', 'ADBase'} & relatives)
islist = lambda o: not isstring(o) and isinstance(o, (list, set))
isdict = lambda o: not isstring(o) and (isinstance(o, (dict, defaultdict, UserDict)) or hasattr(o, 'as_dict') or (hasattr(o, 'data') and isinstance(o.data, dict)))
isnumber = lambda o: isinstance(o, (float, int))

def sanitize_list(o) -> list:
  result = []
 
  for e in sorted(o, key=lambda x: str(x)):
    if isdict(e): _ = sanitize_dict(e)
    elif islist(e): _ = sanitize_list(e)
    elif isnumber(e): _ = e
    else: _ = str(e) if e else None
    result.append(_)
  return result

def sanitize_dict(o) -> dict:
  result = {}
  if hasattr(o, 'as_dict'): d = o.as_dict()
  elif hasattr(o, 'data') and isinstance(o.data, dict): d = o.data
  else: d = dict(o)

  _ = [k for k in KEYS_FIRST if k in d]
  ordered_keys = _ + sorted([k for k in d.keys() if k not in KEYS_FIRST and k not in KEYS_DROP])
  for k in ordered_keys:
    v = d[k]
    if k in KEYS_DROP: continue
    elif k in KEYS_FORCE_STRING: _ = str(v)
    elif isdict(v): _ = sanitize_dict(v)
    elif islist(v): _ = sanitize_list(v)
    elif isnumber(v): _ = v
    else: _ = str(v) if v else None
    result[str(k)] = _
  return result

def dict_sanitize(data: dict, sort_keys=False) -> dict:
  """Convert nested complex data types for json.dumps or yaml.dumps"""
  if islist(data): return sanitize_list(data)
  elif isdict(data): return sanitize_dict(data)
  else: raise ValueError(f"Unable to sanitize {data}")

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
  yaml.add_representer(tuple, yaml.representer.Representer.represent_dict)
  with open(filename,'w+') as f: 
    try: yaml.dump(redata, f, indent=2, Dumper=IndentedListDumper, sort_keys=False, width=2147483647)
    except Exception as err:
      error = f"Error dumping {filename}\n{err} {type(err)}\n{pfy(redata)}\n\n"
      with open(filename+'_error.txt','w+') as ferr: ferr.write(error)


def dict_from_yml(filename:str):
  yml_root = filename.rsplit('/', 1)[0]

  def yml_include(loader, node):
    filename = yml_root+'/'+node.value
    with open(filename, "r") as f: return yaml.load(f, Loader=yaml.FullLoader)

  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, yaml.representer.Representer.represent_dict)
  yaml.add_constructor("!include", yml_include, Loader=yaml.FullLoader)

  with open(filename) as f: return dict(yaml.load(f, Loader=yaml.FullLoader))
# endregion

# 2Do Templates
def dict_template_populate(o, data: dict = {}, excludes:list = []):
  """ 
    Returns new dictionary, copy of o with all templatable elements filled-in from data 
    
    This function is recursive

    Keys with value == 'DEL' are removed from result
    Keys with '$' in value are treated as templates and filled-in from data
  """
  # def flatcopy(data):
  #   redata = {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool, list)) and k not in excludes}
  #   return redata

  def __tp(o, data: dict):
    if not data: data = {}
    # data = flatcopy(data)

    if not o: result = None
    elif isinstance(o, dict):
      result = {}
      for k, old in o.items():
        if k in excludes or inspect.isfunction(old): 
          new = old
        else:
          # !!! data | o   
          # !!! o | data
          new = __tp(old, o | data)
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

  if isinstance(o, dict):
    _ = o.get('data') or o
  else:
    _ = str(o)
  result = __tp(_, data)
  return result

# region Loggin and Time helpers: now_ts, now_str
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
# endregion

# region Tracing decorators
TA_BEFORE = 'before'
TA_AFTER = 'after'
TA_INSTEAD = 'instead'
TAs = [TA_BEFORE, TA_AFTER, TA_INSTEAD]
def _tracer(tracer: Callable = None, action: str = None) -> Callable:
  def decorator(method: Callable):
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

# endregion

# region PCP - Pretty Colored Print and colorize - utility
def _print_terminal_color_table():
  for b in "34":
    s = ""
    for f in "01234567": s += _colorize_list(f+b+';1', f"{f+b+';1'}") + "  "
    print(s)

  for f in range(0, 15):
    s = _colorize_list(f"38;5;{f};1", f"38;5;{f};1")+"  "
    print(s)

  for b in range(0, 1):
    s = ""
    for f in range(0, 15): s += _colorize_list(f"38;5;{f};1", f"38;5;{f};1")+"  "
    print(s)

TERMINAL_COLORS = {
    'NONE':  '0m',             # No color (text)
    'DIM':   '38;5;8;1',        # Dim gray (text)
    'BRIGHT':'36;1',            # Bright cyan (text)
    'BW':    '38;5;15;1',       # Bright white (text)
    'DW':    '38;5;7;1',        # Dark white (text)

    'GRAY1': '38;5;234',        # Darkest gray (text)
    'GRAY2': '38;5;240',        # Gray (text)
    'GRAY3': '38;5;246',        # Gray (text)
    'GRAY4': '38;5;252',        # Lightest gray (text)

    'BY':    '38;5;11;1',       # Bright yellow (text)
    'DY':    '38;5;3;1',        # Dark yellow (text)
    'BG':    '38;5;10;1',       # Bright green (text)
    'DG':    '38;5;2;1',        # Dark green (text)

    'BB':    '3;30;44',         # Black on Blue (background)
    'DB':    '38;5;4;1',        # Dark blue (text)

    'BC':    '38;5;6;1',        # Bright cyan (text)
    'DC':    '38;5;14;1',       # Dark cyan (text)
    'BM':    '38;5;13;1',       # Bright magenta (text)
    'DM':    '38;5;5;1',        # Dark magenta (text)
    'BR':    '38;5;9;1',        # Bright red (text)
    'DR':    '38;5;1;1',        # Dark red (text)

    'INFO':  '34;1',            # Bright blue (text, for info messages)
    'WHITE': '0;30;47',         # Black on White (background)
    'YELLOW':'0;30;43',         # Black on Yellow (background)
    'RED':   '0;30;41',         # Black on Red (background)
    'BLUE':  '0;30;44',         # Black on Blue (background)
    'GREEN': '0;30;42',         # Black on Green (background)

    'ORANGE':'38;5;208;1',      # New: Bright orange (text)
    'DO':    '38;5;130;1',      # New: Dark orange (text)
    'PURPLE':'38;5;129;1',      # New: Bright purple (text)
    'DP':    '38;5;90;1',       # New: Dark purple (text)
    'PINK':  '38;5;200;1',      # New: Bright pink (text)
    'DPINK': '38;5;132;1',      # New: Dark pink (text)
    'BGOLD': '38;5;220;1',      # New: Bright gold (text)
    'DGOLD': '38;5;178;1',      # New: Dark gold (text)
    
    'WRED':  '0;37;41',         # White on Red (background)
    'WBLUE': '0;37;44',         # White on Blue (background)
    'WGREEN':'0;37;42',         # White on Green (background)
    'WGRAY': '0;30;47',         # Black on Light Gray (background)
    'WPINK': '0;30;45',         # Black on Pink (background)
    'WPURPLE':'0;37;45'         # White on Purple (background)
}

# TERMINAL_COLORS = {
#     'NONE':   '0m',
#     'DIM':    '38;5;8;1',
#     'BRIGHT': '36;1',
#     'BW':     '38;5;15;1', # White
#     'DW':    '38;5;7;1', # Dark White (7)

#     'GRAY1':  '38;5;234', # Gray
#     'GRAY2':  '38;5;240', # Gray
#     'GRAY3':  '38;5;246', # Gray
#     'GRAY4':  '38;5;252', # Gray


#     'BY':     '38;5;11;1', # Yellow
#     'DY':     '38;5;3;1', # Dark Yellow (3)
#     'BG':     '38;5;10;1', # Green
#     'DG':     '38;5;2;1', # Dark Green (2)

#     'BB':     '3;30;44', # Blue
#     'DB':     '38;5;4;1', # Dark Blue (4)

#     'BC':     '38;5;6;1', # Cyan
#     'DC':     '38;5;14;1', # Dark Cyan (6)
#     'BM':     '38;5;13;1', # Magenta
#     'DM':     '38;5;5;1', # Dark Magenta (5)
#     'BR':     '38;5;9;1', # Red
#     'DR':     '38;5;1;1', # Dark Red (1)

#     'INFO':   '34;1',
#     'WHITE':  '0;30;47',
#     'YELLOW': '0;30;43',
#     'RED':    '0;30;41',
#     'BLUE':   '0;30;44',
#     'GREEN':  '0;30;42'
# }

def pcp(*a, **kw) -> str:
  """
  Pretty colored print. Supports two kinds of input:
    level, msg: compatible with default logger
    [args]: used by self.Dargs to colorize output
  Returns: colored string
  
  Parameters:
    verbose: adds pfy(kwargs) to output
    silent: suppresses local print output
    
  """
  if len(a) == 1 and isinstance(a[0], tuple): a = list(a[0])
  out = ""
  verbose = kw.pop('verbose', False)
  silent = kw.pop('silent', False)
  level = kw.pop('level', None)
  if 'msg' in kw:
    msg = kw.get('msg')
    out = _colorize_log(msg=msg, level=level)
    if a: out += _colorize_list(a)
  else:
    out = _colorize_list(a)
  if kw and verbose: out += pfy(kw)
  if not silent: print(out)
  return out

remove_prefixes = lambda s, prefixes: next((s.removeprefix(prefix) for prefix in prefixes if s.startswith(prefix)), s)
SHORTEN_BY_PREFIX = ['process_', '_cb_']
IGNORE_FUNCTIONS = ['dpcp', 'trace', 'pcp', 'Trace']
def dpcp(*a, globdict=None, **kw) -> str:
  """ Version of pcp that adds info on where it was called from """
  def is_traced(name=None, globdict=None):
    if not globdict: globdict = globals().get('_TRACES', {})

    if not name or name not in globdict: return globdict.get('all')
    else: return globdict.get(name)

  frame = inspect.currentframe().f_back

  while frame.f_back:
    frame = frame.f_back
    filename, line_number, func_name, _, _ = inspect.getframeinfo(frame)
    if func_name not in IGNORE_FUNCTIONS: break
    func_name = remove_prefixes(func_name, SHORTEN_BY_PREFIX)

  if not is_traced(func_name, globdict): return 
  module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
  if not is_traced(module, globdict): return
  if 'self' in frame.f_locals: 
    if not is_traced(class_name := frame.f_locals["self"].__class__.__name__, globdict): return
    _ = ['GRAY2', f"{class_name}", 'GRAY3', f".{func_name}"]
  else: _ = ['GRAY3', f".{func_name}"]

  _ += list(a)
  return pcp(*_) 

def _colorize_log(msg, level=None, *args):
  if isinstance(msg, tuple): msg = _colorize_list(msg)
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

def _colorize_list(l: list):
  """ Colorizes list of strings. Strings separated with space unless start with . or / """
  result = []
  color = None
  for e in [str(e) for e in l if e]:
    e = str(e)
    if e in TERMINAL_COLORS: color = e; continue
    elif color: elem = _colorize(color, str(e))
    else: elem = str(e)

    if e[0] in "./" and result: result += [elem]
    elif not result: result += [elem]
    else: result += [' '+elem]
  return ''.join(result)

def _colorize(color:str, text:str, fmt=None):
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
# endregion