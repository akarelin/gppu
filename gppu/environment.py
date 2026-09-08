"""Environment: what an app knows about where it runs, and how to reach the rest of the fleet.

The basic level needs no configuration file: platform, host and user, the path grammar in
paths.j2, and the trace rules gppu keeps. The fleet level is the RAN configuration (hosts,
platforms, locations, shares, mounts); it loads only when an app asks, with `fleet()` or a
`topology:` in its own config. Then the fleet methods answer what the RAN tools used to work
out for themselves: which targets a task runs on, how to ssh to one, where a location is.

Lookups are strict, as in Y2: a missing key raises, nothing has a default.
"""

from __future__ import annotations

import getpass
import os
import platform as _platform
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

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


@dataclass(frozen=True)
class Target:
  """One place a task runs: a host, or one environment (wsl, win) of a workstation."""
  host: str
  env: str
  label: str
  platform: str
  shell: str
  address: str
  user: str
  port: int
  home: str
  local_home: Path | None
  python: str
  memory: str
  export_root: str
  repos: tuple[str, ...]

  @property
  def local(self) -> bool: return self.host == Environment.host and self.platform == Environment.platform


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

  # -- fleet: hosts and targets -----------------------------------------------------------
  @staticmethod
  def facts(platform: str) -> dict:
    """The platform's facts: home, ran, memory, python, statusline, export root."""
    return Environment.glob_dict(f'platforms/{platform}')

  @staticmethod
  def hosts(*groups: str) -> dict[str, dict]:
    """Host rows by name, from these groups (Workstations, Servers, Pies) or all of them."""
    tree = Environment.glob_dict('hosts')
    return {name: row for group, members in tree.items() if not groups or group in groups for name, row in members.items()}

  @staticmethod
  def host_row(name: str) -> dict:
    hosts = Environment.hosts()
    if name not in hosts: raise KeyError(name)
    return hosts[name]

  @staticmethod
  def targets(*groups: str, repo: str | None = None) -> Iterator[Target]:
    """Every place a task can run in these groups: a host, or each environment of a workstation.
    `repo` keeps only hosts carrying that repository."""
    for name, row in Environment.hosts(*groups).items():
      if repo and repo not in row['repos']: continue
      for env, entry in (row['envs'].items() if 'envs' in row else (('', row),)):
        yield Environment._target(name, row, env, entry)

  @staticmethod
  def _target(name: str, row: dict, env: str, entry: dict) -> Target:
    platform = entry['platform']
    facts = Environment.facts(platform)
    home = entry['profile_dir'] if platform == 'windows' else facts['home']
    local = name == Environment.host and platform == Environment.platform
    if not local: local_home = None
    elif platform == 'wsl': local_home = Path(facts['local_home'])
    else: local_home = Path(home).expanduser()
    return Target(
      host=name, env=env, label=f'{name}.{entry["label"]}' if env else name, platform=platform, shell=entry['shell'],
      address=entry['ssh_host'], user=entry['ssh_user'] if 'ssh_user' in entry else Environment.glob('globals/ssh_user'),
      port=int(entry['port']) if 'port' in entry else SSH_PORT, home=home.replace('\\', '/'), local_home=local_home,
      python=facts['python'], memory=entry['memory'], export_root=entry['export_root'], repos=tuple(row['repos']))

  @staticmethod
  def target(name: str, env: str = '') -> Target:
    row = Environment.host_row(name)
    return Environment._target(name, row, env, row['envs'][env] if env else row)

  @staticmethod
  def here() -> Target:
    """This machine and platform, as a target."""
    for target in Environment.targets():
      if target.local: return target
    raise KeyError(f'{Environment.host} ({Environment.platform}) is not in the fleet')

  @staticmethod
  def ssh(target: Target | str, env: str = '') -> list[str]:
    """The ssh command that reaches a target; append the remote command."""
    if isinstance(target, str): target = Environment.target(target, env)
    command = ['ssh', '-o', f"ConnectTimeout={Environment.glob('globals/ssh_connect_timeout')}", '-o', 'BatchMode=yes']
    if target.port != SSH_PORT: command += ['-p', str(target.port)]
    return command + [f'{target.user}@{target.address}']

  # -- fleet: locations and shares --------------------------------------------------------
  @staticmethod
  def mount(nas: str, share: str) -> str:
    """Where a Linux host mounts `share` of `nas`."""
    return str(Environment.paths.mount(Environment.glob_dict('shares'), nas, share))

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
