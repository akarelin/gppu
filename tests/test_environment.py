from pathlib import Path

import pytest

from gppu import Env, Environment, dict_from_yml


def test_platform_vocabulary():
  assert Environment.platform in ('windows', 'wsl', 'debian', 'macos')
  assert Environment.host and Environment.user


def test_path_grammar():
  assert Environment.win('SD') == 'C:\\Users\\Alex\\SD'
  assert Environment.win('', '/') == 'C:/Users/Alex'
  assert Environment.d('Dev/RAN', '/') == 'D:/Dev/RAN'
  assert Environment.wsl(Environment.d('SD.Lake/inbox')) == '/mnt/d/SD.Lake/inbox'
  assert Environment.wsl(Environment.d('')) == '/mnt/d'
  assert Environment.wsl_unc('') == '\\\\wsl$\\Debian\\home\\alex'
  assert Environment.posix('macos', '.claude/plans') == '/Users/alex/.claude/plans'
  assert Environment.tilde('RAN') == '~/RAN'
  assert Environment.volume('SD') == '/volume1/SD'


def test_jinja_config_loads_lists_and_grows_env(tmp_path: Path):
  (tmp_path / 'lists').mkdir()
  (tmp_path / 'lists' / 'hosts.yaml').write_text('Servers:\n  seven: {fqdn: 7.c.karel.in}\n  trix: {fqdn: 6.c.karel.in}\n', encoding='utf-8')
  (tmp_path / 'hosts.yaml.j2').write_text(
    "{% import 'paths.j2' as p %}\n{% set rows = load('lists/hosts.yaml') %}\n"
    "{% for group, members in rows.items() %}\n{{ group }}:\n{% for name, host in members.items() %}\n"
    "  {{ name }}:\n    hostname: {{ host.fqdn }}\n    ssh_host: {{ name }}\n    home: {{ p.posix('debian', '') | yaml }}\n"
    "{% endfor %}\n{% endfor %}\n", encoding='utf-8')
  (tmp_path / 'root.yaml').write_text("globals: {ssh_user: alex, ssh_connect_timeout: 5}\nhosts: !include hosts.yaml.j2\nshares: {s1: {hostname: s1.karel.in, shares: [{name: SD}, {name: Public, mount: /mnt/Public}]}}\n"
    "locations:\n  sd:\n    name: SD\n    local/seven: {linux: /mnt/S1/SD}\n    smb/s1: {smb: SD}\n", encoding='utf-8')
  data = dict_from_yml(tmp_path / 'root.yaml')
  assert data['hosts']['Servers']['trix'] == {'hostname': '6.c.karel.in', 'ssh_host': 'trix', 'home': '/home/alex/'}

  Environment.fleet(tmp_path / 'root.yaml')
  assert Environment.ssh('trix') == ['ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes', 'alex@trix']
  assert Environment.mount('s1', 'SD') == '/mnt/S1/SD'
  assert Environment.mount('s1', 'Public') == '/mnt/Public'
  assert Environment.local('sd', host='seven', platform='debian') == '/mnt/S1/SD'
  assert Environment.smb('sd') == '//s1.karel.in/SD'
  with pytest.raises(KeyError): Environment.glob('hosts/Servers/kolme')
  Env.reset()
