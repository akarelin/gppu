"""gppu's version as pip shows it: every build stays on its release (3.7.11), so the label after `+` tells builds apart.
It is when the commit the build was made from was committed, in local time, as YYYYMMDDHHMM: the same on alex-pc, on
the runners and in the release files. The rest of setuptools-scm's configuration is in pyproject.toml."""
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from setuptools import setup


def committed(version) -> str:
    seconds = int(subprocess.check_output(['git', 'log', '-1', '--format=%ct'], text=True))
    return '+' + datetime.fromtimestamp(seconds, ZoneInfo('America/Los_Angeles')).strftime('%Y%m%d%H%M')


setup(use_scm_version={'local_scheme': committed})
