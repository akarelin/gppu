"""Environment and State: what an app knows at startup, the Y2 way.

Environment is the basic level, with no configuration file: platform, host, user, home,
os and the trace rules. Once `Environment.from_env` has loaded the app's configuration —
and through its `!include` of the shared one, everything the fleet knows — lookups into
it are strict, and the questions a utility used to answer for itself are rules of the
configuration — its macros — reached as Environment.<section>.<rule>(...): where a
location is on a host, what its address is on a connection, which path an address means
here, how a command runs on a host. gppu knows no rule by name.

State holds what the configuration constructs. Every section carrying `templates` is a
table; every other mapping in it is a row keyed by its uid. A row resolves through the
section's TemplateSet — the template builds the default dict from the uid, the row
updates it with what differs — is checked against the tables it references, and is
built by the class its `kind` names — the app that cares registers it, any other app
gets a plain _DC carrying the kind. A row marked `service` registers in
State.services. Construction runs once, at startup.
"""

from __future__ import annotations

import getpass
import os
import platform as _platform
import socket
from pathlib import Path
from typing import Any

from .gppu import TRACE_RULES, Env, TemplateSet, _DC, deepget, detect_os

SECTION_KEYS = ('macros', 'generators', 'templates')   # what a table section holds beside its rows
_MISSING = object()


def platform_name() -> str:
  """The platform vocabulary of the shared configuration: windows, wsl, debian, macos."""
  system = _platform.system()
  if system == 'Windows': return 'windows'
  if system == 'Darwin': return 'macos'
  if 'WSL_DISTRO_NAME' in os.environ or 'microsoft' in _platform.release().lower(): return 'wsl'
  return 'debian'


class _Sections(type):
  """Environment.<section> is that table's rules, once the configuration is loaded."""
  def __getattr__(cls, name: str):
    if name in State.templates: return cls._Rules(name, State.templates[name])
    raise AttributeError(f'no table named {name!r}')


class Environment(metaclass=_Sections):
  os = detect_os()
  platform: str = platform_name()
  host: str = socket.gethostname().split('.')[0].lower()
  user: str = getpass.getuser()
  home: Path = Path.home()

  # -- loading: gppu Env underneath, State constructed on top --------------------------
  @staticmethod
  def from_env(name: str | None = None, app_path: Path | None = None) -> None:
    Env.from_env(name=name, app_path=app_path)
    State.load()

  @staticmethod
  def from_dict(d: dict) -> None:
    Env.from_dict(d)
    State.load()

  @staticmethod
  def trace() -> dict: return TRACE_RULES

  # -- lookups: strict, as in Y2 — a missing key raises, nothing has a default -------------
  @staticmethod
  def glob(path: str) -> Any:
    result = deepget(path, Env.data, default=_MISSING)
    if result is _MISSING: raise KeyError(path)
    return result

  @staticmethod
  def glob_list(path: str) -> list:
    result = Environment.glob(path)
    if not isinstance(result, list): raise TypeError(f'{path} is not a list')
    return result

  @staticmethod
  def glob_dict(path: str) -> dict:
    result = Environment.glob(path)
    if not isinstance(result, dict): raise TypeError(f'{path} is not a mapping')
    return result

  # -- rules: a macro of a table section, reachable as Environment.<section>.<macro>(...) --
  class _Rules:
    def __init__(self, section: str, templates: TemplateSet):
      self._section, self._globals = section, templates.environment.globals
    def __getattr__(self, name: str):
      rule = self._globals.get(name)
      if not callable(rule): raise AttributeError(f'{self._section} defines no rule {name!r}')
      return rule

class State:
  tables: dict[str, dict[str, Any]] = {}
  templates: dict[str, TemplateSet] = {}
  services: dict[str, Any] = {}
  kinds: dict[str, type] = {}

  @staticmethod
  def register(**kinds: type) -> None:
    """The classes a template's `kind` may name."""
    State.kinds.update(kinds)

  @staticmethod
  def reset() -> None:
    for section in State.tables: delattr(State, section)
    State.tables, State.templates, State.services = {}, {}, {}

  @staticmethod
  def rows(section: str) -> dict[str, dict]:
    """The rows of a table section: every mapping in it that is not macros, generators or templates."""
    return {uid: row for uid, row in Env.glob_dict(section).items() if uid not in SECTION_KEYS and isinstance(row, dict)}

  @staticmethod
  def load() -> None:
    """Construct every table of the loaded configuration."""
    State.reset()
    sections = [name for name, content in Env.data.items() if isinstance(content, dict) and 'templates' in content]
    tables = {name: State.rows(name) for name in sections}   # what a macro sees under a table's name: its rows,
    for section in sections:                                 # resolved once the table is, so a table resolved
      if hasattr(State, section): raise ValueError(f'{section}: a table cannot be named after a State member')
      templates = Env.template_set(section, Environment=Environment, State=State, **tables)   # later sees what an
      resolved = {uid: templates.resolve({'uid': uid, **row}) for uid, row in tables[section].items()}   # earlier one computed
      tables[section].clear(); tables[section].update(resolved)
      table = {}
      for uid, data in resolved.items():
        obj = State.kinds.get(data.get('kind'), _DC)(data=data)   # the app that cares registers the class
        table[uid] = obj
        if data.get('service'): State.services[uid] = obj
      State.tables[section], State.templates[section] = table, templates
      setattr(State, section, table)
