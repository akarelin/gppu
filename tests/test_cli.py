"""The command line overrides the configuration: --key value sets a key, a bare --flag sets it True."""
from gppu import Env


def test_env_takes_pairs_and_flags_and_leaves_the_programs_arguments():
  Env.from_dict({'chrome': {'profile': 'Default'}, 'days': 1})
  Env.from_argv(['mount', 'Archive*', '--chrome/profile', 'Work', '--days', '7', '--verbose'])
  assert Env.glob('chrome/profile') == 'Work' and Env.glob('days') == '7' and Env.glob('verbose') is True
  assert not {'mount', 'Archive*'} & Env.data.keys()
