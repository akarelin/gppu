"""The command line overrides an app's own configuration: --key value sets a key, a bare --flag sets it True."""
import sys

from gppu import App


def test_an_app_takes_pairs_and_flags_and_leaves_the_programs_arguments(monkeypatch):
  monkeypatch.setattr(sys, 'argv', ['app', 'mount', 'Archive*', '--chrome/profile', 'Work', '--days', '7', '--verbose'])
  app = App(config={'chrome': {'profile': 'Default'}, 'days': 1})
  assert app.my('chrome/profile') == 'Work' and app.my('days') == 7 and app.my('verbose') is True   # .. a value is read as YAML
  assert not {'mount', 'Archive*'} & app.my('').keys()
