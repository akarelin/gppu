"""Environment and State: what an app knows at startup, the Y2 way.

Environment is the basic level, with no configuration file: platform, host, user, home,
os and the trace rules. Once `Environment.from_env` has loaded the app's configuration —
and through its `!include` of the shared one, everything the fleet knows — lookups into
it are strict, and the questions a utility used to answer for itself are rules of the
configuration — its macros — reached as Environment.<table>.<rule>(...): where a
location is on a host, what its address is on a connection, which path an address means
here, how a command runs on a host. gppu knows no rule by name.

State holds what the configuration constructs. Both are single instances, as in Y2. Every key of the configuration carrying
`templates` is a table; every other mapping under it is a row keyed by its uid. A row
resolves through the table's TemplateSet — the template builds the default dict from the uid, the row
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

TABLE_KEYS = ('macros', 'generators', 'templates')   # what a table holds beside its rows
_MISSING = object()


def platform_name() -> str:
  """The platform vocabulary of the shared configuration: windows, wsl, debian, macos."""
  system = _platform.system()
  if system == 'Windows': return 'windows'
  if system == 'Darwin': return 'macos'
  if 'WSL_DISTRO_NAME' in os.environ or 'microsoft' in _platform.release().lower(): return 'wsl'
  return 'debian'


class _Environment:
  os = detect_os()
  platform: str = platform_name()
  host: str = socket.gethostname().split('.')[0].lower()
  user: str = getpass.getuser()
  home: Path = Path.home()

  # -- loading: gppu Env underneath, State constructed on top --------------------------
  def from_env(self, name: str | None = None, app_path: Path | None = None) -> None:
    Env.from_env(name=name, app_path=app_path)
    State.load()

  def from_dict(self, d: dict) -> None:
    Env.from_dict(d)
    State.load()

  def trace(self) -> dict: return TRACE_RULES

  # -- lookups: strict, as in Y2 — a missing key raises, nothing has a default -------------
  def glob(self, path: str) -> Any:
    result = deepget(path, Env.data, default=_MISSING)
    if result is _MISSING: raise KeyError(path)
    return result

  def glob_list(self, path: str) -> list:
    result = self.glob(path)
    if not isinstance(result, list): raise TypeError(f'{path} is not a list')
    return result

  def glob_dict(self, path: str) -> dict:
    result = self.glob(path)
    if not isinstance(result, dict): raise TypeError(f'{path} is not a mapping')
    return result

  # -- rules: Environment.<table>.<rule>(...) is a macro of that table ---------------------
  def __getattr__(self, table: str):
    if table in State.templates: return _Rules(table, State.templates[table])
    raise AttributeError(f'no table named {table!r}')


class _Rules:
  def __init__(self, table: str, templates: TemplateSet):
    self._table, self._globals = table, templates.environment.globals

  def __getattr__(self, name: str):
    rule = self._globals.get(name)
    if not callable(rule): raise AttributeError(f'{self._table} defines no rule {name!r}')
    return rule


class _State:
  def __init__(self) -> None:
    self.tables: dict[str, dict[str, Any]] = {}
    self.templates: dict[str, TemplateSet] = {}
    self.services: dict[str, Any] = {}
    self.kinds: dict[str, type] = {}

  def register(self, **kinds: type) -> None:
    """The classes a template's `kind` may name."""
    self.kinds.update(kinds)

  def reset(self) -> None:
    for table in self.tables: delattr(self, table)
    self.tables, self.templates, self.services = {}, {}, {}

  def rows(self, table: str) -> dict[str, dict]:
    """The rows of a table: every mapping under its key that is not macros, generators or templates."""
    return {uid: row for uid, row in Env.glob_dict(table).items() if uid not in TABLE_KEYS and isinstance(row, dict)}

  def load(self) -> None:
    """Construct every table of the loaded configuration."""
    self.reset()
    names = [name for name, content in Env.data.items() if isinstance(content, dict) and 'templates' in content]
    rows = {name: self.rows(name) for name in names}   # what a macro sees under a table's name: its rows, resolved
    for name in names:                                  # once the table is, so a table resolved later sees what an
      if hasattr(self, name): raise ValueError(f'{name}: a table cannot be named after a State member')   # earlier one computed
      templates = Env.template_set(name, Environment=Environment, State=self, **rows)
      resolved = {uid: templates.resolve({'uid': uid, **row}) for uid, row in rows[name].items()}
      rows[name].clear(); rows[name].update(resolved)
      table = {}
      for uid, data in resolved.items():
        obj = self.kinds.get(data.get('kind'), _DC)(data=data)   # the app that cares registers the class
        table[uid] = obj
        if data.get('service'): self.services[uid] = obj
      self.tables[name], self.templates[name] = table, templates
      setattr(self, name, table)


Environment = _Environment()
State = _State()
