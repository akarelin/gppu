"""The command line overrides an app's own configuration: --key value sets a key, a bare --flag sets it True."""
from gppu import App


def test_an_app_takes_pairs_and_flags_and_leaves_the_programs_arguments():
  app = App(config={'chrome': {'profile': 'Default'}, 'days': 1},
            argv=['mount', 'Archive*', '--chrome/profile', 'Work', '--days', '7', '--verbose'])
  assert app.my('chrome/profile') == 'Work' and app.my('days') == '7' and app.my('verbose') is True
  assert not {'mount', 'Archive*'} & app.my('').keys()
