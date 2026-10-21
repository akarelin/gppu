"""CliApp as it was in gppu/gppu.py until 2026-10-20: main run once and its result printed as JSON. A full CLI app, with
a schema, is not gppu's; a program whose command line overrides its configuration sets APP['cli']."""
import json
import sys
from typing import Any

from gppu.gppu import Env, _Base


class CliApp(_Base):
  """Runs ``main`` once. The command line is already over the configuration, as for every program, ``--since 3d``;
  ``main`` is the action; what it returns is printed as JSON on stdout, logs go to stderr.

  Usage::

      from gppu import CliApp
      class Archive(CliApp):
        def main(self) -> dict:
          since = self.my('since')
      if __name__ == '__main__': Archive.cli()
  """

  def main(self) -> Any: raise NotImplementedError(f'{type(self).__name__} defines no main')

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> Any:
    """Start from the command line: the command line over the configuration, build the app, then ``main``. ``argv``
    stands in for the program's own."""
    Env._data()
    Env.from_argv(sys.argv[1:] if argv is None else argv)
    app = cls()
    result = app.main()
    if result is not None: print(json.dumps(result, indent=2, default=str))
    return result
