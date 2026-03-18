# gppu.ad - Home Automation Types and Base Classes

`gppu.ad` provides home automation types (paths, topics, slugs, entity IDs) and the `DC` pseudo-dataclass. Originally built for home automation (AppDaemon/HASS), but the types are general-purpose.

```python
from gppu.ad import y2list, y2path, y2topic, y2slug, y2eid, DC
```

## y2list Family

Token-based list types that split strings on a separator and rejoin on `str()`. All inherit from `UserList`.

### y2list

Generic tokenized list. Splits on word boundaries (regex `[a-zA-Z0-9]+`) when no token is set.

```python
from gppu.ad import y2list

l = y2list('hello_world_123')  # ['hello', 'world', '123']
str(l)     # 'helloworld123'
l.head     # 'hello'
l.tail     # '123'
```

### y2path

`/` separator. Path-like.

```python
from gppu.ad import y2path

p = y2path('sensors/temp/room')  # ['sensors', 'temp', 'room']
str(p)     # 'sensors/temp/room'
p.head     # 'sensors'
p.tail     # 'room'

# Multiple args are concatenated
p = y2path('sensors', 'temp/room')  # ['sensors', 'temp', 'room']
```

### y2topic

MQTT topic. Inherits `y2path`, adds wildcard detection.

```python
from gppu.ad import y2topic

t = y2topic('home/+/temperature')
t.is_wildcard()  # True (contains + or #)

t = y2topic('home/living_room/temperature')
t.is_wildcard()  # False
```

### y2slug

`_` separator. Strips `@domain` from input.

```python
from gppu.ad import y2slug

s = y2slug('user_name@domain.com')  # ['user', 'name']
str(s)  # 'user_name'
```

### Common y2list methods

All y2list types share these methods:

```python
p = y2path('sensors/temp/room/main')

# Query
p.startswith('sensors')        # True (cross-token aware: _ and / are interchangeable)
p.endswith('main')             # True
p.startswith(['sensors', 'x']) # True (any match)
p.endswith(['main', 'x'])     # True (any match)

# Mutating extraction
p.pophead()                    # 'sensors' (removes and returns first element)
p.poptail()                    # 'main' (removes and returns last element)
p.extract('temp')              # 'temp' (removes by value, returns it or None)
p.discard('room')              # removes all occurrences (no return)

# Suffix/prefix removal
p = y2path('sensors/temp/room/main')
p.popsuffix('room/main')       # 'room/main' (removes and returns suffix, or None)
p.popprefix('sensors/temp')    # 'sensors/temp' (removes and returns prefix, or None)
p.popxfix('temp')              # tries popsuffix first, then popprefix

# Other
p.iadd('extra/parts')          # extends data in-place
p.upper()                      # 'SENSORS/TEMP/ROOM/MAIN'
p.lower()                      # 'sensors/temp/room/main'
p.to_json()                    # str(p)
```

## y2eid - Entity ID

Namespace-aware entity identifier with format: `domain.slug@namespace`.

```python
from gppu.ad import y2eid

eid = y2eid('light.kitchen_main@yala')
eid.entity_id  # 'light.kitchen_main'
eid.seid       # 'light.kitchen_main@yala' (full string)
eid.domain     # 'light'
eid.slug       # y2slug('kitchen_main')
eid.head       # 'kitchen'
eid.tail       # 'main'
eid.ns         # 'yala'

# Defaults: domain='entity', ns='yala'
eid = y2eid('kitchen')  # 'entity.kitchen@yala'

# Comparison and hashing (by string representation)
eid == 'light.kitchen_main@yala'  # True
{eid: 'value'}                    # hashable

# startswith/endswith delegate to slug
eid.startswith('kitchen')  # True
eid.endswith('main')       # True

# Construction from various sources
eid = y2eid({'entity_id': 'light.kitchen'})           # from dict
eid = y2eid(other_eid)                                 # from another y2eid
eid = y2eid(obj_with_entity_id_and_namespace)          # from object with attributes
eid = y2eid('light.kitchen', ns='custom_namespace')    # explicit namespace
```

Class-level defaults can be overridden:
```python
y2eid.default_ns = 'my_system'
y2eid.default_domain = 'device'
```

## DC - Pseudo-DataClass

`UserDict`-based dataclass that auto-generates typed properties from `__annotations__`.

```python
from gppu.ad import DC

class Device(DC):
    name: str
    brightness: int
    tags: list
    config: dict
    active: bool

d = Device(name='lamp', brightness=100, tags=['living_room'])
d.name        # 'lamp' (typed property, returns '' if missing for str)
d.brightness  # 100 (returns 0 if missing for int)
d.tags        # ['living_room'] (returns [] if missing for list)
d.config      # {} (returns {} if missing for dict)
d.active      # None (returns None if missing for bool)
d.data        # {'name': 'lamp', 'brightness': 100, 'tags': ['living_room']}

# Properties are settable
d.name = 'new_lamp'
d.data  # {'name': 'new_lamp', ...}
```

### Supported types

Built-in type map (`_DC_BASE_TYPE_MAP`): `str`, `int`, `float`, `bool`, `list`, `dict`, `set`, `y2eid`.

Extend with custom types via `_DC_TYPE_MAP`:
```python
class MyDC(DC):
    _DC_TYPE_MAP = DC._DC_TYPE_MAP | {'MyCustomType': MyCustomType}
    field: MyCustomType
```

### Init pipeline

Initialization runs through `_INIT_STEPS` (list of callables). Default is `[_init_from_kw]` which merges kwargs and `data` kwarg into `self.data`.

Override for custom initialization:
```python
class MyDC(DC):
    name: str

    def _my_init(self, **kw):
        self._init_from_kw(**kw)
        # custom post-processing
        if not self.name:
            self.name = 'default'

    _INIT_STEPS = [_my_init]
```

### Annotations from inheritance

Annotations are collected from the full MRO, so subclasses inherit parent properties:
```python
class Base(DC):
    name: str
    id: int

class Extended(Base):
    extra: list

e = Extended(name='x', id=1, extra=[1, 2])
e.name   # 'x' (inherited)
e.extra  # [1, 2]
```
