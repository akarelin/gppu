"""Connections: the services an app uses, configured once and handed to it by type.

A Provider is the class that reaches a service; an instance of it, with its connection parameters, is a
Connection. The ``connections`` table of the configuration holds one row per Connection, keyed by uid. A row's
``provider`` names the class, by its scheme or by ``module.Class``; the rest of the row is its parameters, and
``!secret`` supplies what is secret. This is Windmill's resource (the row), resource type (the Provider) and
``$var:`` (``!secret``).

    connections:
      pg-lake:  {provider: gppu.data.Postgres, dsn: !secret pg-lake-dsn}
      mqtt-i2:  {provider: mqtt, host: i2, port: 1883}

An app asks for one by annotating a parameter of ``main`` with the Provider class (see gppu.params); code asks with
``connection(uid)``. One instance per uid per process, shared by everyone who asks.
"""
from __future__ import annotations

import importlib
from copy import deepcopy
from typing import Any, Mapping

from .gppu import Env, is_table_key


class Provider:
  """Reaches one kind of service. An instance is a Connection: the Provider with its connection parameters.

  A subclass declares ``scheme`` and reads its parameters from ``self.connection``. It connects on first use and
  releases in ``close``; constructing one never touches the network.

  Attributes:
    scheme (str): What the ``provider`` field of a row may say to name this class: postgres, mqtt, file.
    uid (str): The row it was built from; empty when built in code.
    connection (dict[str, Any]): The row's parameters.
  """
  scheme = ''
  schemes: dict[str, type[Provider]] = {}

  def __init_subclass__(cls, **kw):
    super().__init_subclass__(**kw)
    if cls.scheme: Provider.schemes[cls.scheme] = cls

  def __init__(self, connection: Mapping[str, Any] | None = None, uid: str = '') -> None:
    self.uid = uid
    self.connection = deepcopy(dict(connection)) if connection is not None else {}

  def close(self) -> None: pass

  def __repr__(self) -> str: return f'{type(self).__name__}({self.uid})'


_open: dict[str, Provider] = {}


def provider_class(name: str) -> type[Provider]:
  """The Provider a row's ``provider`` field names: a scheme already imported, or ``module.Class``."""
  if name in Provider.schemes: return Provider.schemes[name]
  module, _, attr = name.rpartition('.')
  if not module: raise ValueError(f'{name}: unknown provider; name it as module.Class')
  cls = getattr(importlib.import_module(module), attr)
  if not (isinstance(cls, type) and issubclass(cls, Provider)): raise TypeError(f'{name}: not a Provider')
  return cls


def connections() -> dict[str, dict]:
  """The rows of the ``connections`` table, resolved through its templates when it has them."""
  if 'connections' not in Env.data: return {}
  table = Env.glob_dict('connections')
  rows = {uid: {'uid': uid, **row} for uid, row in table.items() if not is_table_key(uid) and isinstance(row, dict)}
  if 'templates' in table:
    rules = Env.template_set('connections')
    rows = {uid: rules.resolve(row) for uid, row in rows.items()}
  return rows


def connection(uid: str) -> Provider:
  """The Connection configured under uid, built once."""
  if uid not in _open:
    rows = connections()
    if uid not in rows: raise KeyError(f'no connection {uid!r} in configuration')
    row = rows[uid]
    params = {k: v for k, v in row.items() if k not in ('uid', 'provider')}
    _open[uid] = provider_class(row['provider'])(params, uid=uid)
  return _open[uid]


def of_type(kind: type[Provider]) -> list[str]:
  """The uids of the configured Connections whose Provider is kind or a subclass of it."""
  return [uid for uid, row in connections().items() if 'provider' in row and issubclass(provider_class(row['provider']), kind)]


def close_all() -> None:
  for conn in _open.values(): conn.close()
  _open.clear()
