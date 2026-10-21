"""CliApp's tests, archived with CliApp."""
"""CliApp: the command line overrides keys of the configuration."""
from gppu import CliApp, Env


class Report(CliApp):
  def main(self) -> dict: return {'days': self.my('days'), 'dry_run': self.my('dry_run'), 'logs': self.my('logs')}


def test_no_arguments_runs_on_the_configuration():
  Env.from_dict({'days': 1, 'dry_run': False, 'logs': ['a'], 'report': {'days': 3}})
  assert Report(name='report').name == 'report'
  assert Report.cli([]) == {'days': 1, 'dry_run': False, 'logs': ['a']}


def test_the_command_line_overrides_keys():
  Env.from_dict({'days': 1, 'dry_run': False, 'logs': ['a']})
  assert Report.cli(['--days', '7', '--dry_run', 'true', '--logs', '[b, c]']) == {'days': '7', 'dry_run': 'true', 'logs': '[b, c]'}


def test_env_takes_pairs_and_flags_and_leaves_the_programs_arguments():
  Env.from_dict({'chrome': {'profile': 'Default'}, 'days': 1})
  Env.from_argv(['mount', 'Archive*', '--chrome/profile', 'Work', '--days', '7', '--verbose'])
  assert Env.glob('chrome/profile') == 'Work' and Env.glob('days') == '7' and Env.glob('verbose') is True
  assert not {'mount', 'Archive*'} & Env.data.keys()

