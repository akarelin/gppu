"""Environment: what an app knows about where it runs, and how to reach the rest of the fleet.

The basic level needs no configuration file: platform, host and user, the path grammar in
paths.j2, and the trace rules gppu keeps. The fleet level is the RAN configuration (hosts,
platforms, locations, shares, mounts); it loads only when an app asks, with `fleet()` or a
`topology:` in its own config, and the connection and access methods answer from it.

Lookups are strict, as in Y2: a missing key raises, nothing has a default.
"""

from __future__ import annotations

import getpass
import os
import platform as _platform
import socket
from pathlib import Path
from typing import Any

from .gppu import TRACE_RULES, Env, JinjaFileEnvironment, deepget, detect_os

PACKAGE_DIR = Path(__file__).parent
PATHS_TEMPLATE = 'paths.j2'
SSH_PORT = 22
PATH_FORMS = {'windows': 'windows', 'wsl': 'wsl', 'debian': 'linux', 'macos': 'mac'}   # platform -> key of a location's local path
_MISSING = object()


def _platform_name() -> str:
  """The platform vocabulary of the RAN configuration: windows, wsl, debian, macos."""
  system = _platform.system()
  if system == 'Windows': return 'windows'
  if system == 'Darwin': return 'macos'
  if 'WSL_DISTRO_NAME' in os.environ or 'microsoft' in _platform.release().lower(): return 'wsl'
  return 'debian'


class Environment:
  os = detect_os()
  platform: str = _platform_name()
  host: str = socket.gethostname().split('.')[0].lower()
  user: str = getpass.getuser()
  home: Path = Path.home()

  paths = JinjaFileEnvironment(PACKAGE_DIR).get_template(PATHS_TEMPLATE).module

  # -- configuration: gppu Env underneath, strict on top ---------------------------------
  @staticmethod
  def from_env(name: str | None = None, app_path: Path | None = None) -> None:
    Env.from_env(name=name, app_path=app_path)

  @staticmethod
  def fleet(topology: str | Path) -> None:
    """Load the fleet configuration (RAN/_config/_ran.yaml.j2) as the environment."""
    Env.from_dict({'topology': str(topology)})

  @staticmethod
  def glob(path: str) -> Any:
    result = deepget(path, Env.data, default=_MISSING)
    if result is _MISSING: raise KeyError(path)
    return result

  @staticmethod
  def glob_int(path: str) -> int: return int(Environment.glob(path))

  @staticmethod
  def glob_list(path: str) -> list:
    result = Environment.glob(path)
    if not isinstance(result, list): raise TypeError(path)
    return result

  @staticmethod
  def glob_dict(path: str) -> dict:
    result = Environment.glob(path)
    if not isinstance(result, dict): raise TypeError(path)
    return result

  @staticmethod
  def trace() -> dict: return TRACE_RULES

  # -- paths: the grammar in paths.j2, one macro each ------------------------------------
  @staticmethod
  def win(sub: str = '', sep: str = '\\') -> str: return str(Environment.paths.win(sub, sep))
  @staticmethod
  def d(sub: str = '', sep: str = '\\') -> str: return str(Environment.paths.d(sub, sep))
  @staticmethod
  def wsl(path: str) -> str: return str(Environment.paths.wsl(path))
  @staticmethod
  def wsl_unc(sub: str = '') -> str: return str(Environment.paths.wsl_unc(sub))
  @staticmethod
  def posix(platform: str, sub: str) -> str: return str(Environment.paths.posix(platform, sub))
  @staticmethod
  def tilde(sub: str) -> str: return str(Environment.paths.tilde(sub))
  @staticmethod
  def volume(share: str) -> str: return str(Environment.paths.volume(share))

  @staticmethod
  def home_path(sub: str) -> str:
    """`sub` under the home directory of this host, in this platform's form."""
    if Environment.platform == 'windows': return Environment.win(sub)
    return Environment.posix(Environment.platform, sub)

  # -- fleet: hosts, connections and locations ------------------------------------------
  @staticmethod
  def mount(nas: str, share: str) -> str:
    """Where a Linux host mounts `share` of `nas`."""
    return str(Environment.paths.mount(Environment.glob_dict('shares'), nas, share))

  @staticmethod
  def host_row(name: str) -> dict:
    for group in Environment.glob_dict('hosts').values():
      if name in group: return group[name]
    raise KeyError(name)

  @staticmethod
  def ssh(name: str, env: str | None = None) -> list[str]:
    """The ssh command that reaches a host, or one of a workstation's environments (wsl, win)."""
    host = Environment.host_row(name)
    entry = host['envs'][env] if env else host
    settings = Environment.glob_dict('globals')
    port = int(entry.get('port') or host.get('port') or SSH_PORT)
    user = entry.get('ssh_user') or host.get('ssh_user') or settings['ssh_user']
    address = entry.get('ssh_host') or host.get('ssh_host') or host['hostname']
    command = ['ssh', '-o', f"ConnectTimeout={settings['ssh_connect_timeout']}", '-o', 'BatchMode=yes']
    if port != SSH_PORT: command += ['-p', str(port)]
    return command + [f'{user}@{address}']

  @staticmethod
  def local(location: str, host: str | None = None, platform: str | None = None) -> str:
    """The path of a location on a host: this host and platform unless told otherwise."""
    place = Environment.glob_dict(f'locations/{location}')[f"local/{host or Environment.host}"]
    return place[PATH_FORMS[platform or Environment.platform]]

  @staticmethod
  def smb(location: str) -> str:
    """The UNC path of a location's NAS share."""
    place = Environment.glob_dict(f'locations/{location}')
    nas = next(key.split('/')[1] for key in place if key.startswith('smb/'))
    return f"//{Environment.glob(f'shares/{nas}/hostname')}/{place[f'smb/{nas}']['smb']}"
