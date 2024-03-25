import pprint
import yaml
import re
import inspect
import logging

from typing import TypeVar, Union, get_origin, get_args, Callable, Any

from string import Template

from collections import defaultdict, UserDict, UserList
from datetime import datetime

VER_GPPU_BASE = '2.9.2'
VER_GPPU_BUILD = '240322'
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


def deepget_int(path: str, d: dict, default=None) -> int:
  """ Returns int at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, int) else default


def deepget_list(path: str, d: dict, default=None) -> list:
  """ Returns list at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, list) else default


def deepget_dict(path: str, d: dict, default=None) -> dict:
  """ Returns dict at path, or default if not found """
  _ = deepget(path, d, default)
  return _ if isinstance(_, dict) else default


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
  # ! Support for Null keys is not finished and its unclear if it is needed anymore
  ordered_keys = _ + sorted([str(k) if k else '?' for k in d.keys() if k not in KEYS_FIRST and k not in KEYS_DROP])
  for k in ordered_keys:
    if k == '?': v = d.get(None)
    else: v = d.get(k)
    
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
    if node.value[0] == '/':
      filename = node.value
    else: 
      filename = yml_root+'/'+node.value
    with open(filename, "r") as f: return yaml.load(f, Loader=yaml.FullLoader)

  yaml.add_representer(defaultdict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(UserDict, yaml.representer.Representer.represent_dict)
  yaml.add_representer(set, yaml.representer.Representer.represent_list)
  yaml.add_representer(tuple, yaml.representer.Representer.represent_dict)
  yaml.add_constructor("!include", yml_include, Loader=yaml.FullLoader)

  with open(filename) as f: return dict(yaml.load(f, Loader=yaml.FullLoader))
# endregion


# region Templates
def dict_template_populate(o, data: dict = {}, excludes:list = []):
  """ 
    Returns new dictionary, copy of o with all templatable elements filled-in from data 
    
    This function is recursive

    Keys with value == 'DEL' are removed from result
    Keys with '$' in value are treated as templates and filled-in from data
  """
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
    #_ = o.get('data') or o
    _ = o.get('data', {}) | o
  else:
    _ = str(o)
  result = __tp(_, data)
  return result
# endregion


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


# region y2xxx
# xx                                                                                        
# xx y2list, y2path and y2slug                                                              
# xx                                                                                        
""" y2list-based: y2path, y2slug"""
def any2list(o, token: str = None) -> list:
  result = []
  if o:
    if hasattr(o, 'data'): o = o.data
    if isinstance(o, (list, tuple)): result = [_ for _ in o if _]
    elif token: result = str(o).split(token)
    else: result = re.findall('[a-zA-Z0-9]+', str(o))
  return result


class y2list(UserList):
  def __init__(self, o=None):
    self.data = any2list(o)
    self.token = ""


  def __str__(self): return self.token.join(self.data)
  def __repr__(self): return self.token.join(self.data)
  def __hash__(self): return hash(str(self))
  def __eq__(self, other):
    if hasattr(other, 'data'): return self.data == other.data
    else: return str(self) == str(other)


  def upper(self): return str(self).upper()
  def lower(self): return str(self).lower()
  def encode(self, encoding='utf-8', errors='strict'): return str(self.data).encode(encoding, errors)
  def iadd(self, o): self.data += any2list(o)
  def to_json(self): return str(self)


  @property
  def head(self) -> str: return self.data[0] if len(self.data) > 0 else None
  @property
  def tail(self) -> str: return self.data[-1] if len(self.data) > 0 else None


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
  def pophead(self) -> str: return self.data.pop(0) if len(self.data) > 0 else None
  def poptail(self) -> str: return self.data.pop(-1) if len(self.data) > 0 else None


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
  def __init__(self, *args):
    data = []
    for a in args: data += any2list(a)
    self.data = any2list(data)
    self.token = '/'


class y2topic(y2path):
  def is_wildcard(self) -> bool: return self.data & "#+"


class y2slug(y2list):
  def __init__(self, o=None): 
    if '@' in str(o): o = str(o).split('@')[0]
    self.data = any2list(o, '_')
    self.token = '_'


class y2eid:
  def __init__(self, o=None, ns=None, **kwargs):
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

# endregion


# region PCP - Pretty Colored Print and colorize - utility

class _TColorHack(type):
  def __getitem__(cls, key): return getattr(cls, str(key), None)
  def __contains__(cls, key): return hasattr(cls, str(key))

  def print(cls):
    l = []
    for name, colorcode in cls.dir(): l.append(colorcode, name)
    print(_colorize_list(l))


class TColor(metaclass=_TColorHack):
  NONE = '0m'             # No color (text)
  DIM = '38;5;8;1'        # Dim gray (text)
  BRIGHT = '36;1'         # Bright cyan (text)
  BW = '38;5;15;1'        # Bright white (text)
  DW = '38;5;7;1'         # Dark white (text)

  GRAY1 = '38;5;234'      # Darkest gray (text)
  GRAY2 = '38;5;240'      # Gray (text)
  GRAY3 = '38;5;246'      # Gray (text)
  GRAY4 = '38;5;252'      # Lightest gray (text)

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

  INFO = '34;1'           # Bright blue (text, for info messages)
  WHITE = '0;30;47'       # Black on White (background)
  YELLOW = '0;30;43'      # Black on Yellow (background)
  RED = '0;30;41'         # Black on Red (background)
  BLUE = '0;30;44'        # Black on Blue (background)
  GREEN = '0;30;42'       # Black on Green (background)

  WRED = '0;37;41'        # White on Red (background)
  WBLUE = '0;37;44'       # White on Blue (background)
  WGREEN = '0;37;42'      # White on Green (background)
  WGRAY = '0;30;47'       # Black on Light Gray (background)
  WPINK = '0;30;45'       # Black on Pink (background)
  WPURPLE = '0;37;45'     # White on Purple (background)
  #WYELLOW = '0;37;43'     # White on Yellow (background)
  WYELLOW = '7;49;93'     # White on Yellow (background)


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
SEVERITY_COLORS = {'Error': 'WRED', 'Warn': 'WYELLOW', 'Info': 'WBLUE', 'Debug': 'GRAY4', None: 'WPURPLE'}
def dpcp(*a, conditional=None, rules={}, no_prefix: bool=False, severity=None, **kw) -> str:
  """ Version of pcp that adds info on where it was called from """
  def is_traced(name=None):
    if not conditional: return True

    if not name or name not in rules: return rules.get('all')
    else: return rules.get(name)

  if not conditional and rules: conditional = True
  frame = inspect.currentframe().f_back

  while frame.f_back:
    frame = frame.f_back
    filename, line_number, func_name, _, _ = inspect.getframeinfo(frame)
    if func_name not in IGNORE_FUNCTIONS: break
    func_name = remove_prefixes(func_name, SHORTEN_BY_PREFIX)

  if not is_traced(func_name): return 
  module = filename.rsplit('/', 1)[-1].rsplit('.', 1)[0]
  if not is_traced(module): return
  if not is_traced(f"{module}.{func_name}"): return

  if 'self' in frame.f_locals: 
    if not is_traced(class_name := frame.f_locals["self"].__class__.__name__): return
    if not is_traced(f"{class_name}.{func_name}"): return
    _ = ['GRAY2', f"{class_name}", 'GRAY3', f".{func_name}"]
  else: _ = ['GRAY3', f".{func_name}"]

  if severity: 
    _ = [SEVERITY_COLORS.get(severity, SEVERITY_COLORS[None]), severity] + _

  if no_prefix: _ = list(a)
  else: _ += list(a)

  return pcp(*_, **kw)


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
  colorcode = None
  for e in [e for e in l if e]:
    if isinstance(e, TColor): colorcode = e; continue
    e = str(e)
    if TColor[e]: colorcode = TColor[e]; continue
    elif colorcode: elem = _colorize(text=str(e), colorcode=colorcode)
    else: elem = str(e)

    if e[0] in "./" and result: result += [elem]
    elif not result: result += [elem]
    else: result += [' '+elem]
  return ''.join(result)

def _colorize(text:str, colorcode:str, fmt=None):
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
  ESC = '\u001b'
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
    maxlen = safe_int(fmt, 0)

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
      out += _colorize_list(record.args)
    if verbose and hasattr(record, 'kwargs'):
      out += pfy(record.kwargs)  # Assuming pfy is a pretty print function for kwargs

    return out
    
class PrettyColoredHandler(logging.StreamHandler):
  def emit(self, record):
    silent = getattr(record, 'silent', False)
    if not silent:
      super().emit(record)

# logger = logging.getLogger(__name__)
# logger.addHandler(logging.FileHandler(f"{__name__}.log"))
# logger.addHandler(logging.StreamHandler())
# endregion
