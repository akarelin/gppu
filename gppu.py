# General purpose python utilities
import pprint
import yaml

from collections import defaultdict
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

def dict_sanitize(data, as_is=True):
  """Convert nested complex data types for json.dumps or yaml.dumps"""
  def sanitize_list(l) -> list:
    result = []
    for e in l:
      if isinstance(e, (dict, defaultdict)): _ = sanitize_dict(e)
      elif isinstance(e, (list, set)): _ = sanitize_list(e)
      else: _ = str(e) if e else None
      if as_is or _: result.append(_)
    return result

  def sanitize_dict(d) -> dict:
    result = {}
    for k, v in [(str(k), v) for k, v in d.items() if as_is or v]:
      if isinstance(v, (dict, defaultdict)): _ = sanitize_dict(v)
      elif isinstance(v, (list, set)): _ = sanitize_list(v)
      elif isinstance(v, (float, int, str)): _ = v
      else: _ = str(v) if v else None
      if as_is or _: result[k] = _
    return result

  if isinstance(data, (dict, defaultdict)): return sanitize_dict(data)
  elif isinstance(data, (list, set)): return sanitize_list(data)
  else: raise ValueError(f"Unable to sanitize {data}")

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

"""Logging"""
def timestamp(): return datetime.now().strftime("%Y%m%d.%H%M%S")
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

def log_colored(msg, level=None, *args, **kwargs):
  msg = colorize_log(msg, level)
  print(msg)
  return msg

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

# def NONE(text, fmt=None): return colorpad('0m', text, fmt)
# #def DIM(text, fmt=None): return colorpad('38;5;19', text, fmt)
# def DIM(text, fmt=None): return colorpad('38;5;8;1', text, fmt) # 30;1 = brigth black or 37;1 = lightgrey
# def BRIGHT(text, fmt=None): return colorpad('36;1', text, fmt) # 36;1 = bright magenta
# def BW(text, fmt=None): return colorpad('38;5;7;1', text, fmt) # 36;1 = bright magenta
# def BY(text, fmt=None): return colorpad('38;5;11;1', text, fmt) # 36;1 = bright magenta
# def BG(text, fmt=None): return colorpad('38;5;10;1', text, fmt) # 36;1 = bright magenta
# def INFO(text, fmt=None): return colorpad('34;1', text, fmt)
# def WHITE(text, fmt=None): return colorpad('0;30;47', text, fmt)
# def YELLOW(text, fmt=None): return colorpad('0;30;43', text, fmt)
# def RED(text, fmt=None): return colorpad('0;37;41', text, fmt)
# def BLUE(text, fmt=None): return colorpad('0;30;44', text, fmt)
# def GREEN(text, fmt=None): return colorpad('0;37;42', text, fmt)

def colorize_list(l:list):
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
