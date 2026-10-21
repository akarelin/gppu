"""CliApp: the command line overrides keys of the configuration."""
import pytest

from gppu import CliApp, Env


class Report(CliApp):
  def main(self) -> dict: return {'days': self.my('days'), 'dry_run': self.my('dry_run'), 'logs': self.my('logs')}


def test_no_arguments_runs_on_the_configuration():
  Env.from_dict({'days': 1, 'dry_run': False, 'logs': ['a'], 'report': {'days': 3}})
  assert Report(name='report').name == 'report'
  assert Report.cli([]) == {'days': 1, 'dry_run': False, 'logs': ['a']}


def test_the_command_line_overrides_keys_read_as_yaml():
  Env.from_dict({'days': 1, 'dry_run': False, 'logs': ['a']})
  assert Report.cli(['--days', '7', '--dry_run', 'true', '--logs', '[b, c]']) == {'days': 7, 'dry_run': True, 'logs': ['b', 'c']}


def test_arguments_are_key_value_pairs():
  Env.from_dict({})
  with pytest.raises(SystemExit): Report.cli(['--days'])
  with pytest.raises(SystemExit): Report.cli(['days', '7'])

