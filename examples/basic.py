"""The simplest program on gppu: load the environment, then read it.

Run it bare, or give it settings on the command line:
  python examples/basic.py
  python examples/basic.py --greeting Hi --trace_rules/all --log_file C:/.cache/basic.log
A basic.yaml or config.yaml beside it, when there is one, holds the same settings.
"""
import sys

from gppu import Debug, Env, Info, Warn, glob

Env.from_env()                # basic.yaml or config.yaml beside it
Env.from_argv(sys.argv[1:])   # its command line goes over it

Info('started on', Env.host, Env.platform, 'as', Env.user)
if glob('greeting'): Info(glob('greeting'), 'from', Env.name)
Debug('a Debug line, shown when the trace rules let it')
Warn('a warning')


class Greeter:
  def greet(self): Info('a line from a method names its class and method')


Greeter().greet()
