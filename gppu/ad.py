from __future__ import annotations

import re
import sys
import logging

from copy import deepcopy
from pathlib import Path
from collections import UserList, UserDict
from functools import partial
from typing import Any, Optional, ClassVar, List, Callable

from .gppu import (
    TRACE_RULES, Env,
    deepget, deepget_int, deepget_float, deepget_list, deepget_dict,
    Debug, Info, Warn, Error, Dump,
    _logger,
    _init_logger_base,
    _colorize_log, _colorize_list, pfy,
)


def init_logger(name: str = 'gppu', trace_rules: dict | None = None) -> None:
  _init_logger_base(name, trace_rules)
  from . import gppu as _gppu
  Logger.trace_rules = _gppu.TRACE_RULES
  for cls in list(mixin_Logger.__subclasses__()):
    cls._logger = _gppu._logger.getChild(cls.__name__)
    for n, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)):
      setattr(cls, n, staticmethod(partial(fn, logger=cls._logger)))


def init_logger_ad(name: str, trace_rules: dict, trace_folder: str = '.') -> None:
  init_logger(name, trace_rules)
  Logger.trace_folder = trace_folder

class PrettyColoredFormatter(logging.Formatter):
  def format(self, record):
    verbose = getattr(record, 'verbose', False)
    level = record.levelname
    msg = super().format(record)

    out = _colorize_log(msg=msg, level=level)
    if hasattr(record, 'args') and record.args:
      args = list(record.args) if not isinstance(record.args, list) else record.args
      out += _colorize_list(args)

    kwargs = getattr(record, 'kwargs', None)
    if verbose and isinstance(kwargs, dict): out += pfy(kwargs)

    return out


class PrettyColoredHandler(logging.StreamHandler):
  def emit(self, record):
    silent = getattr(record, 'silent', False)
    if not silent: super().emit(record)


# @@      mixin class                                                           ==
class _mixin: pass


class mixin_Config(_mixin):
  _my: dict[str, Any] = {}

  def _config_from_key(self, key: str) -> None: self._my.update(Env.glob_dict(key))
  def _config_copy(self, other: mixin_Config) -> None: self._my = dict(other._my)
  def _config_from_dict(self, d: dict) -> None: self._my = deepcopy(d)
  def _config_from_env(self) -> None: self._my = deepcopy(Env.data)

  def my(self, path, default=None) -> Any: return deepget(path, self._my, default=default)
  def my_int(self, path, default: int = 0) -> int: return deepget_int(path, self._my, default=default)
  def my_float(self, path, default: float = float('nan')) -> float: return deepget_float(path, self._my, default=default)
  def my_list(self, path, default: list = []) -> list: return deepget_list(path, self._my, default=default or [])
  def my_dict(self, path, default: dict = {}) -> dict: return deepget_dict(path, self._my, default=default or {})

class Logger:
  """Namespace wrapper exposing logging helpers."""
  trace_folder: str = ''
  trace_rules: dict = TRACE_RULES

  @staticmethod
  def Debug(*a, **kw): Debug(*a, **kw)
  @staticmethod
  def Info(*a, **kw): Info(*a, **kw)
  @staticmethod
  def Warn(*a, **kw): Warn(*a, **kw)
  @staticmethod
  def Error(*a, **kw): Error(*a, **kw)
  @staticmethod
  def Dump(*a, **kw): Dump(*a, **kw)


class protocol_Logger:
  Debug: Callable[..., Any]
  Info : Callable[..., Any]
  Warn : Callable[..., Any]
  Error: Callable[..., Any]
  Dump : Callable[..., Any]


class mixin_Logger(protocol_Logger, _mixin):
  _logger: logging.Logger

  @classmethod
  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    cls._logger = _logger.getChild(cls.__name__)
    for name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)): setattr(cls, name, staticmethod(partial(fn, logger=cls._logger)))

  def __init__(self, *a, **kw):
    super(mixin_Logger, self).__init__(*a, **kw)
    # instance shortcuts re-use the class-level bound functions
    for name in ('Debug', 'Info', 'Warn', 'Error', 'Dump'): setattr(self, name, getattr(self.__class__, name))

# region y2xxx
# xx
# xx y2list, y2path and y2slug
# xx
""" y2list-based: y2path, y2slug"""
class y2list(UserList):
  data: List[Any]
  token: str


  def _any2list(self, o) -> list:
    result = []
    if o:
      if hasattr(o, 'data'): o = o.data
      if isinstance(o, (list, tuple)): result = [_ for _ in o if _]
      elif self.token: result = str(o).split(self.token)
      else: result = re.findall('[a-zA-Z0-9]+', str(o))
    return result


  def __init__(self, o: Optional[Any] = None) -> None:
    super().__init__()
    self.token = ""
    self.data = self._any2list(o)


  def __str__(self): return self.token.join(self.data)
  def __repr__(self): return self.token.join(self.data)
  def __eq__(self, other: Any) -> bool:
    if hasattr(other, 'data'): return self.data == other.data
    else: return str(self) == str(other)
  def __hash__(self): return hash(str(self))  # type: ignore


  def upper(self): return str(self).upper()
  def lower(self): return str(self).lower()
  def encode(self, encoding='utf-8', errors='strict'): return str(self.data).encode(encoding, errors)
  def iadd(self, o): self.data += self._any2list(o)
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
      self.data = self._any2list(str(self).replace(ix, ''))
      return self.token.join(self._any2list(ix))
  def popprefix(self, ix):
    if self.startswith(ix):
      if '_' in ix and self.token != '_': ix = ix.replace('_', self.token)
      elif '/' in ix and self.token != '/': ix = ix.replace('/', self.token)
      self.data = self._any2list(str(self).replace(ix, ''))
      return self.token.join(self._any2list(ix))
  def popxfix(self, ix): return self.popsuffix(ix) or self.popprefix(ix)


class y2path(y2list):
  def __init__(self, *args):
    data = []
    self.token = '/'

    for a in args: data += self._any2list(a)
    self.data = self._any2list(data)


class y2topic(y2path):
  def is_wildcard(self) -> bool: return bool(set(self.data) & {"#", "+"})


class y2slug(y2list):
  def __init__(self, o):
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)


class y2eid:
  ns: str
  domain: str
  slug: y2slug
  default_ns: ClassVar[str] = 'yala'
  default_domain: ClassVar[str] = 'entity'
  _ready: bool = False

  def __bool__(self) -> bool: return self._ready

  def __init__(self, o: Any, ns: Optional[str] = None, **kw):
    self._ready = False
    if not o: raise ValueError("y2eid: empty input")

    ns = ns or self.default_ns

    if isinstance(o, y2eid): s = str(o)
    elif isinstance(o, dict): s = str(o.get('entity_id',""))
    elif isinstance(o, str): s = o
    elif hasattr(o, 'entity_id') and hasattr(o, 'namespace'): s = f"{o.entity_id}@{o.namespace}"
    elif hasattr(o, 'entity_id') and hasattr(o, 'ns'): s = f"{o.entity_id}@{o.ns}"
    elif hasattr(o, 'seid'): s = o.seid
    else: raise ValueError

    self.ns = ns
    self.domain = ''
    if '.' in s: self.domain, s = s.split('.',1)
    if '@' in s: s, self.ns = s.rsplit('@',1)
    self.ns = self.ns or self.default_ns
    self.domain = self.domain or self.default_domain
    self.slug = y2slug(s)

    for k in ['tail', 'head']: setattr(self, k, getattr(self.slug, k))
    self._ready = True


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
  def startswith(self, ix) -> bool: return self.slug.startswith(ix)
  @property
  def entity_id(self) -> str: return f"{self.domain}.{self.slug}" if self._ready else ""
  @property
  def seid(self): return str(self)
# endregion


# region DC - pseudo DataClass
_DC_BASE_TYPE_MAP = {'str': str, 'list': list, 'dict': dict, 'set': set, 'int': int, 'float': float, 'bool': bool, 'None': type(None), 'y2eid': y2eid}


class DC(UserDict):
  _DC_TYPE_MAP: dict[str, type] = _DC_BASE_TYPE_MAP.copy()
  _DC_EXCLUDE_NAMES: list[str] = []


  def _init_from_kw(self, **kw) -> None:
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data


  _INIT_STEPS: list[Callable] = [_init_from_kw]


  def __init_subclass__(cls, **kw) -> None:
    def _simple_type(typ: type | str) -> str:
      typ = str(typ)
      if typ.startswith('list['): return 'list'
      return typ

    super().__init_subclass__(**kw)

    annotations_raw = [(n, t if type(t) == str else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_' and n not in cls._DC_EXCLUDE_NAMES]
    annotations = {n: _simple_type(t) for n, t in annotations_raw}

    mro = [(n, t) for n, t in annotations.items() if n[0] != '_' and t in cls._DC_TYPE_MAP]
    for aname, atype in mro:
      def getter(self, name=aname, atype=atype):
        result = self.data.get(name)
        if result is not None and isinstance(result, cls._DC_TYPE_MAP[atype]): return result
        if not result:
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  def __init__(self, **kw):
    self.data = {}
    for step in self._INIT_STEPS: step(self, **kw)
# endregion


# region Foundation
class _Logger(mixin_Logger): pass


class _Config(mixin_Config):
  _base_path: Path

  def __init__(self, **kw) -> None:
    super().__init__()
    assert Env.initialized, "Env must be initialized"
    key = kw.get('config_key', None)

    if key:
      self._config_from_key(key)
      self._base_path = Path(self.my('base_dir'))
    else:
      self._config_from_env()
      self._base_path = Path('.')

  def my_path(self, path) -> Path: return self._base_path / self.my(path)


class _Base(_Logger, _Config): pass
# endregion
