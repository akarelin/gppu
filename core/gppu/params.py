"""Parameters: what an app's ``main`` asks for, read from its signature, as Windmill reads a script's ``main``.

    def main(self, since: str = '7d', dry_run: bool = False, db: Postgres = 'pg-lake') -> dict:
      \"\"\"Archive what changed.

      Args:
        since: How far back to look.
      \"\"\"

Each parameter is a command-line option, ``--since 3d``, ``--dry-run``, ``--db pg-trix``. A value comes from, in
order: the command line, the app's configuration under the parameter's name, the signature's default. A parameter
annotated with a Provider takes a connection uid and receives the Connection; with no uid given anywhere, the one
configured Connection of that Provider is used, and none or several is an error. Anything still missing is an error.

The same description serves the command line, ``schema`` (JSON Schema, for a form or a REST manifest) and a call
from another app. The first docstring line is the description; ``Args:`` lines are the help.
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from .connections import Provider, connection, of_type
from .gppu import _MISSING, lookup

_JSON_TYPES = {str: 'string', int: 'integer', float: 'number', bool: 'boolean', Path: 'string', dict: 'object', list: 'array'}
_ARG_LINE = re.compile(r'^\s+(\w+)(?:\s*\([^)]*\))?:\s*(.+)$')


@dataclass
class Param:
  name: str
  type: Any
  default: Any
  help: str

  @property
  def required(self) -> bool: return self.default is _MISSING

  @property
  def provider(self) -> type[Provider] | None:
    return self.type if isinstance(self.type, type) and issubclass(self.type, Provider) else None

  @property
  def option(self) -> str: return '--' + self.name.replace('_', '-')


def _unwrap(annotation: Any) -> Any:
  """``X | None`` is X: None is a default, not a type."""
  if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if len(args) == 1: return args[0]
  return annotation


def _help(fn: Callable) -> tuple[str, dict[str, str]]:
  doc = inspect.getdoc(fn) or ''
  lines = doc.splitlines()
  helps, inside = {}, False
  for line in lines:
    if line.strip() in ('Args:', 'Arguments:', 'Parameters:'): inside = True; continue
    if inside and (m := _ARG_LINE.match(line)): helps[m.group(1)] = m.group(2)
    elif inside and line and not line[0].isspace(): inside = False
  return (lines[0] if lines else ''), helps


def parameters(fn: Callable) -> list[Param]:
  hints = typing.get_type_hints(fn)
  _, helps = _help(fn)
  return [Param(name, _unwrap(hints.get(name, str)), _MISSING if p.default is p.empty else p.default, helps.get(name, ''))
          for name, p in inspect.signature(fn).parameters.items()
          if name not in ('self', 'cls') and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]


def convert(param: Param, value: Any) -> Any:
  """value as the parameter's type. A command line gives strings; configuration gives YAML types."""
  kind, origin = param.type, typing.get_origin(param.type)
  if value is None: return None
  if param.provider: return value if isinstance(value, Provider) else connection(value)
  if origin is Literal:
    if value not in typing.get_args(kind): raise ValueError(f'{param.name}: {value!r} is not one of {typing.get_args(kind)}')
    return value
  if origin is list or kind is list:
    items = value if isinstance(value, list) else [value]
    inner = (typing.get_args(kind) or (str,))[0]
    return [inner(v) for v in items]
  if kind is dict or origin is dict: return json.loads(value) if isinstance(value, str) else dict(value)
  if kind is bool and isinstance(value, str): return value.lower() in ('1', 'true', 'yes', 'on')
  return kind(value) if isinstance(kind, type) and not isinstance(value, kind) else value


def parser(fn: Callable, prog: str) -> argparse.ArgumentParser:
  description, _ = _help(fn)
  cli = argparse.ArgumentParser(prog=prog, description=description, argument_default=argparse.SUPPRESS)
  cli.add_argument('--schema', action='store_true', help='print the parameters as JSON Schema and exit')
  for p in parameters(fn):
    help = p.help + (f' (connection uid of {p.provider.__name__})' if p.provider else '')
    if p.type is bool: cli.add_argument(p.option, dest=p.name, action=argparse.BooleanOptionalAction, help=help)
    elif typing.get_origin(p.type) is list or p.type is list: cli.add_argument(p.option, dest=p.name, nargs='*', help=help)
    elif typing.get_origin(p.type) is Literal: cli.add_argument(p.option, dest=p.name, choices=typing.get_args(p.type), help=help)
    elif p.provider: cli.add_argument(p.option, dest=p.name, choices=of_type(p.provider), help=help)
    else: cli.add_argument(p.option, dest=p.name, help=help)
  return cli


def resolve(fn: Callable, given: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
  """The keyword arguments for fn: given, else config under the parameter's name, else the default, else the one
  configured Connection of a Provider parameter. Missing or ambiguous raises."""
  unknown = set(given) - {p.name for p in parameters(fn)}
  if unknown: raise TypeError(f'{fn.__qualname__}: no parameter {sorted(unknown)}')
  kwargs = {}
  for p in parameters(fn):
    if p.name in given: value = given[p.name]
    elif (found := lookup(p.name, dict(config))) is not _MISSING: value = found
    elif not p.required: value = p.default
    elif p.provider:
      uids = of_type(p.provider)
      if len(uids) != 1: raise LookupError(f'{p.name}: {len(uids)} connections of {p.provider.__name__} {uids}; pass {p.option} <uid>')
      value = uids[0]
    else: raise LookupError(f'{p.name}: required; pass {p.option} or set {p.name} in configuration')
    kwargs[p.name] = convert(p, value)
  return kwargs


def schema(fn: Callable) -> dict:
  """The parameters as JSON Schema; a Connection parameter is a string with ``format: connection-<scheme>``."""
  description, _ = _help(fn)
  props, required = {}, []
  for p in parameters(fn):
    if p.provider: prop = {'type': 'string', 'format': f'connection-{p.provider.scheme or p.provider.__name__}'}
    elif typing.get_origin(p.type) is Literal: prop = {'enum': list(typing.get_args(p.type))}
    else: prop = {'type': _JSON_TYPES.get(typing.get_origin(p.type) or p.type, 'string')}
    if p.help: prop['description'] = p.help
    if not p.required: prop['default'] = str(p.default) if isinstance(p.default, Path) else p.default
    else: required.append(p.name)
    props[p.name] = prop
  return {'type': 'object', 'description': description, 'properties': props, 'required': required}
