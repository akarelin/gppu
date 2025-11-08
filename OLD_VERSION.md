# Pseudo-DataClass with type checking

## Oldest
```python
# region DC - Pseudo-DataClass
def _eval_with_extras(expr: str, frm: FrameType, extra_modules: list[ModuleType] = []):
  ns = {}
  ns.update(frm.f_globals or {})
  ns.update(frm.f_locals or {})
  for m in extra_modules:
    if isinstance(m, ModuleType): ns[m.__name__] = m
    elif isinstance(m, dict): ns.update(m)
    else: ns[type[m].__name__] = m
  return eval(expr, ns, ns)



class DC1(UserDict): # DataClass
  """
    DC is a dict that allows access to dict elements as properties.
    Only elements returned by _get_all_annotations cam be used as properties. 
    DC dynamically adds getter and setter for annotated properties that point to main dict.

    "__init__" is final
    All descendents must use init()
  """
  class _Policy:
    PROHIBITED_ATTRS  = {'data'}
    ALLOWED_TYPES     = {'str', 'list', 'dict', 'set', 'int', 'float', 'bool'}
    PROHIBITED_TYPES = {'type', 'Logger'}

    # @classmethod
    # def _names(cls, types): return {getattr(tp, "__name__", str(tp)) for tp in types}
  
    @classmethod
    def is_allowed(cls, attr: str, hint: object) -> bool:
      st = str(hint)
      # st = _typ2str(hint)
      if st in cls.PROHIBITED_TYPES: return False
      # if st not in cls.ALLOWED_TYPES: return False
      if attr in cls.PROHIBITED_ATTRS: return False
      if attr.startswith('_'): return False
      return True


  @classmethod
  def _policy(cls) -> type[_Policy]:
    return getattr(cls, 'Policy', cls._Policy)


  def __init_subclass__(cls, **kw) -> None:
    super().__init_subclass__(**kw)

    policy = cls._policy()

    # annotations = [(n, t) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items()]
    annotations = [(n, t if type(t) == str else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items()]
      
    mro = [(n, t) for n, t in annotations if policy.is_allowed(n, t)]
    for aname, atype in mro:
      def getter(self, name=aname): 
        if not (result := self.data.get(name)):
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if value and not safe_isinstance(value, type_hint, default=True, extra_modules=[_owner_mod]): 
          raise TypeError(f"Expected type {type_hint} for {name}, got {type(value)} instead.")
        
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  @final
  def __init__(self, **kw):
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data
    if hasattr(self, 'init') and callable(self.init): self.init()


  def __lt__(self, other): return str(self) < str(other)


  @abstractmethod
  def init(self): ...

# endregion
```

## Newer
```python
# region New DC2 - Pseudo-DataClass with type checking
from typing import get_args, get_origin, get_type_hints
# , final
# Any, Optional, Union, 

_DC_DEFAULTS: dict[type[Any], Any] = {
  str: "",
  list: list,      # factory
  dict: dict,      # factory
  set: set,        # factory
  int: 0,
  float: 0.0,
  bool: False,
  type(None): None,
}
_DC_TYPES = tuple(_DC_DEFAULTS.keys())
_DC_NAME2TYPE = {t.__name__: t for t in _DC_TYPES}  | {"None": type(None), "NoneType": type(None)}

class DC2(UserDict):
  def __init_subclass__(cls, **kw) -> None:
    super().__init_subclass__(**kw)

    # raw = inspect.get_annotations(cls, eval_str=False)
    raw = [(n, t if type(t) == str else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_']

    def _resolve_str(s: str) -> Any | None:
      s = s.strip()
      # PEP 604 unions like "str | None | int"
      if "|" in s:
        parts = [p.strip() for p in s.split("|")]
        mapped = [_DC_NAME2TYPE.get(p) for p in parts]
        if any(m is None for m in mapped): return None
        return Union[tuple(mapped)]  # type: ignore[arg-type]
      # typing.Optional[X]
      if s.startswith("Optional[") and s.endswith("]"):
        inner = s[len("Optional["):-1].strip()
        t = _DC_NAME2TYPE.get(inner)
        return None if t is None else Union[t, type(None)]  # type: ignore[index]
      # typing.Union[A, B, ...]
      if s.startswith("Union[") and s.endswith("]"):
        inner = s[len("Union["):-1]
        parts = [p.strip() for p in inner.split(",")]
        mapped = [_DC_NAME2TYPE.get(p) for p in parts]
        if any(m is None for m in mapped): return None
        return Union[tuple(mapped)]  # type: ignore[arg-type]
      # bare name
      return _DC_NAME2TYPE.get(s)

    hints: dict[str, Any] = {}
    for name, anno in raw:
      if isinstance(anno, str):
        r = _resolve_str(anno)
        if r is not None:
          hints[name] = r
      else:
        hints[name] = anno  # already a real type/typing form

    def _allows_none(tp: Any) -> bool:
      if tp is type(None): return True
      return get_origin(tp) is Union and any(t is type(None) for t in get_args(tp))

    def _isinstance_annot(value: Any, tp: Any) -> bool:
      if isinstance(tp, type): return isinstance(value, tp)
      o = get_origin(tp)
      if o is Union: return any(_isinstance_annot(value, t) for t in get_args(tp))
      try:
        return isinstance(value, tp)
      except Exception:
        bases = [t for t in (get_args(tp) if o is Union else ()) if isinstance(t, type)]
        return any(isinstance(value, b) for b in bases)

    def _default_for(tp: Any) -> Any:
      def _pick(t: type[Any]) -> Any:
        d = _DC_DEFAULTS[t]
        return d() if callable(d) and d is not bool else d
      if isinstance(tp, type):
        return _pick(tp) if tp in _DC_DEFAULTS else None
      if get_origin(tp) is Union:
        for t in get_args(tp):
          if isinstance(t, type) and t in _DC_DEFAULTS and t is not type(None):
            return _pick(t)
      return None

    class _Field:
      def __init__(self, anno: Any):
        self._anno = anno
        self._name: str = ""
      def __set_name__(self, owner, name):
        self._name = name
      def __get__(self, obj, owner=None):
        if obj is None: return self
        if not hasattr(obj, "data"): obj.data = {}
        if self._name not in obj.data:
          obj.data[self._name] = _default_for(self._anno)
        return obj.data[self._name]
      def __set__(self, obj, value):
        if value is None:
          if not _allows_none(self._anno):
            raise TypeError(f"{self._name}: None not allowed for {self._anno}")
        elif not _isinstance_annot(value, self._anno):
          raise TypeError(f"{self._name}: expected {self._anno}, got {type(value)}")
        if not hasattr(obj, "data"): obj.data = {}
        obj.data[self._name] = value
      def __delete__(self, obj):
        if hasattr(obj, "data") and self._name in obj.data:
          del obj.data[self._name]

    def _acceptable(a: Any) -> bool:
      if isinstance(a, type): return a in _DC_TYPES
      if get_origin(a) is Union:
        return all(
          (isinstance(t, type) and t in _DC_TYPES) or t is type(None)
          for t in get_args(a)
        )
      return False

    for name, anno in hints.items():
      if name.startswith("_"): continue
      if _acceptable(anno) and not isinstance(getattr(cls, name, None), _Field):
        setattr(cls, name, _Field(anno))
        print(f"Debug: added field {name} of type {anno} to {cls.__name__}")
        Debug("added field", "INFO", name, "DIM", "of type", "INFO", anno, "DIM", "to", "INFO", {cls.__name__})

  @final
  def __init__(self, **kw):
    data = kw.pop("data", {})
    if isinstance(data, str): data = {"data": data}
    self.data = {**data, **kw}
    if hasattr(self, "init") and callable(self.init): self.init()

  @abstractmethod
  def init(self): ...

# endregion
```