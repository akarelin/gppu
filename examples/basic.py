"""The simplest program on gppu: import it, and the program has its environment.

Run it bare, or give it settings on the command line:
  python examples/basic.py
  python examples/basic.py --greeting Hi --trace --log_file C:/.cache/basic.log
A basic.yaml or config.yaml beside it, when there is one, holds the same settings.
"""
from gppu import Debug, Env, Info, Logger, Warn, glob

# The log works from the import: the line says where it came from.
Info('started on', Env.host, Env.platform, 'as', Env.user)

# Settings come from the environment: the configuration file, with the command line over it.
if glob('greeting'): Info(glob('greeting'), 'from', Env.name)

# The program reconfigures its own log through Logger.
if glob('trace'): Logger.trace_rules['all'] = True          # Debug lines show from here on
if glob('log_file'): Logger.enable_file_logging(log_file=glob('log_file'))   # the log goes to the file too

Debug('a Debug line, shown only with --trace')
Warn('a warning')


class Greeter:
  def greet(self): Info('a line from a method names its class and method')


Greeter().greet()
