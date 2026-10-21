"""The simplest program on gppu: import it, and the program has its environment.

Run it bare, or give it settings on the command line:
  python examples/basic.py
  python examples/basic.py --greeting Hi --trace_rules/all --log_file C:/.cache/basic.log
A basic.yaml or config.yaml beside it, when there is one, holds the same settings.
"""
from gppu import APP, Debug, Env, Info, Warn, glob

# What the program says about itself, before anything reads the environment: its command line goes over its
# configuration. APP's other keys are name, config, topology, log_file and trace_rules.
APP['cli'] = True

Info('started on', Env.host, Env.platform, 'as', Env.user)
if glob('greeting'): Info(glob('greeting'), 'from', Env.name)
Debug('a Debug line, shown when the trace rules let it')
Warn('a warning')


class Greeter:
  def greet(self): Info('a line from a method names its class and method')


Greeter().greet()
