"""Environment and State: the shared configuration constructed at startup."""
from pathlib import Path

import pytest

from gppu import Env, Environment, State, TemplateSet
from gppu.gppu import _DC

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'config'


@pytest.fixture(autouse=True)
def environment():
  previous, initialized = Env.data, Env.initialized
  Env.reset(); State.reset()
  yield
  Env.reset(); State.reset()
  Env.data, Env.initialized = previous, initialized


@pytest.fixture
def on(monkeypatch):
  def here(host: str, platform: str) -> None:
    monkeypatch.setattr(Environment, 'host', host)
    monkeypatch.setattr(Environment, 'platform', platform)
    Environment.from_env(name='locations', app_path=EXAMPLE)
  return here


# region TemplateSet: the four rules
def test_templates_stack_in_order_and_the_row_wins():
  templates = TemplateSet(templates={'a': {'x': 1, 'y': 1, 'tags': ['a']}, 'b': {'y': 2, 'tags': ['b']}})
  assert templates.resolve({'template': ['a', 'b'], 'y': 3}) == {'x': 1, 'y': 3, 'tags': ['b']}
  assert templates.resolve({'template': ['b', 'a']})['tags'] == ['a']


def test_a_jinja_value_of_the_template_renders_against_the_row():
  templates = TemplateSet(macros="{% macro address(name) %}{{ name }}.c.karel.in{% endmacro %}",
                          templates={'host': {'hostname': "{{ address(uid) }}", 'port': "{{ base + 1 }}", 'base': 21}})
  assert templates.resolve({'template': 'host', 'uid': 'seven'}) == {'uid': 'seven', 'hostname': 'seven.c.karel.in', 'port': 22, 'base': 21}


def test_a_value_the_row_carries_is_data_and_is_never_rendered():
  templates = TemplateSet(templates={'host': {'hostname': "{{ uid }}.c.karel.in"}})
  assert templates.resolve({'template': 'host', 'uid': 'seven', 'hostname': '{{ literal }}'})['hostname'] == '{{ literal }}'


def test_a_jinja_value_sees_the_values_rendered_before_it():
  templates = TemplateSet(templates={'t': {'first': "{{ uid | upper }}", 'second': "{{ first ~ '!' }}"}})
  assert templates.resolve({'template': 't', 'uid': 'a'})['second'] == 'A!'


def test_an_unknown_template_is_an_error():
  with pytest.raises(KeyError, match="seven: no template named 'missing'"):
    TemplateSet(templates={'host': {}}).resolve({'uid': 'seven', 'template': ['host', 'missing']})


def test_refs_check_values_lists_keys_and_key_patterns():
  templates = TemplateSet(templates={'host': {'refs': {'connections': 'connections', 'smb/*': 'connections', 'platform': ['platforms']}}},
                          connections={'s1': {}, 's9': {}}, platforms={'debian': {}})
  templates.resolve({'uid': 'ok', 'template': 'host', 'connections': ['s1', 's9'], 'smb/s1': 'SD', 'platform': 'debian'})
  with pytest.raises(KeyError, match="bad: connections names 's3', which is not in connections"):
    templates.resolve({'uid': 'bad', 'template': 'host', 'connections': ['s1', 's3']})
  with pytest.raises(KeyError, match="bad: smb/\\* names 's3'"):
    templates.resolve({'uid': 'bad', 'template': 'host', 'smb/s3': 'SD'})
  with pytest.raises(KeyError, match="bad: platform names 'plan9'"):
    templates.resolve({'uid': 'bad', 'template': 'host', 'platform': 'plan9'})


def test_refs_merge_across_stacked_templates():
  templates = TemplateSet(templates={'a': {'refs': {'x': 'xs'}}, 'b': {'refs': {'y': 'ys'}}}, xs={'1': {}}, ys={'2': {}})
  with pytest.raises(KeyError, match="y names '3'"):
    templates.resolve({'uid': 'r', 'template': ['a', 'b'], 'x': '1', 'y': '3'})
# endregion


# region State: tables constructed from the example configuration
def test_every_table_is_constructed_and_registered(on):
  on('alex-laptop', 'windows')
  assert set(State.tables) == {'resources', 'connections', 'hosts', 'locations'}
  assert State.resources['smb']['class'] == 'SmbShare'
  assert State.locations is State.tables['locations']
  assert isinstance(State.locations['sd-lake'], _DC)
  assert State.hosts['seven']['hostname'] == '7.c.karel.in' and State.hosts['trix']['hostname'] == 'trix.c.karel.in'
  assert State.connections['s1']['dir'] == 'S1' and State.hosts['seven']['mount'] == '/mnt'


def test_a_kind_names_a_registered_class(on):
  class Location(_DC):
    name: str
  State.register(Location=Location)
  on('alex-laptop', 'windows')
  assert type(State.locations['sd-lake']) is Location and State.locations['sd-lake'].name == 'SD.Lake'


def test_an_unregistered_kind_is_a_plain_object_carrying_it(on):
  State.kinds.clear()
  on('alex-laptop', 'windows')
  assert type(State.locations['sd-lake']) is _DC and State.locations['sd-lake']['kind'] == 'Location'


def test_a_location_knows_its_addresses_and_its_place_here(on):
  on('alex-laptop', 'windows')
  lake = State.locations['sd-lake']
  assert lake['uris'] == ['smb://s1.karel.in/SD.Lake', 'sd://SD.Lake']   # in the order resources.yaml lists the schemes
  assert lake['local'] == 'D:/SD.Lake' and lake['tags'] == ['synced']
  assert lake['canonical'] == 'sd://SD.Lake' and lake['mirrors'] == ['smb://s1.karel.in/SD.Lake']
  assert State.locations['dev']['canonical'] == 'file://alex-laptop/D:/Dev'   # the folder template's own canonical, over the base one
  assert 'local' not in State.locations['public']           # a share is not on a workstation
  assert State.locations['obsidian']['local'] == 'D:/_'


def test_places_follow_the_rules_per_platform(on):
  on('seven', 'debian')
  assert State.locations['sd-lake']['local'] == '/mnt/S1/SD.Lake'
  assert State.locations['public']['local'] == '/mnt/Public' and Environment.locations.place('public', 'alex-mac', 'macos') == '/Volumes/Public'
  assert State.locations['yellow-config']['local'] == '/mnt/yellow/config'
  assert 'local' not in State.locations['obsidian']
  assert Environment.locations.place('sd-lake', 'alex-pc', 'wsl') == '/mnt/d/SD.Lake'
  assert Environment.locations.place('sd-agents', 'trix', 'debian') == '/home/alex/SD.agents'   # the row's own place for one host
  assert Environment.locations.place('sd-agents', 'seven', 'debian') == '/mnt/S1/SD.agents'


def test_an_address_resolves_to_a_path_on_this_host(on):
  on('alex-laptop', 'windows')
  assert Environment.locations.local_of('sd://SD.Lake/inbox') == 'D:/SD.Lake/inbox'
  assert Environment.locations.local_of('smb://s1.karel.in/Public/x') is None
  assert Environment.locations.folder('sd-lake', 'inbox') == 'D:/SD.Lake/inbox'
  assert Environment.locations.local_of('smb://s1.karel.in/Public/x', 'seven', 'debian') == '/mnt/Public/x'
  assert Environment.locations.uri('sd-lake', 'sd') == 'sd://SD.Lake' and Environment.locations.uri('public', 'sd') is None


def test_a_command_runs_on_a_host_as_its_platform_says(on):
  on('alex-laptop', 'windows')
  assert Environment.hosts.ssh('seven', 'debian') == ['ssh', '-p', '22', 'alex@7.c.karel.in', 'bash', '-s']
  assert Environment.hosts.ssh('alex-pc', 'windows')[:4] == ['ssh', '-p', '22222', 'administrator@alex-pc.c.karel.in']


def test_lookups_are_strict():
  Environment.from_dict({'a': {'b': 1}})
  assert Environment.glob('a/b') == 1
  with pytest.raises(KeyError): Environment.glob('a/c')
  with pytest.raises(AttributeError): Environment.locations


def test_a_dangling_reference_fails_the_load(tmp_path):
  (tmp_path / 'config.yaml').write_text(
    "connections:\n  templates: {box: {}}\n  s1: {template: box}\n"
    "locations:\n  templates:\n    location: {refs: {'smb/*': connections}}\n"
    "  lake: {template: location, smb/s3: Lake}\n", encoding='utf-8')
  with pytest.raises(KeyError, match="lake: smb/\\* names 's3', which is not in connections"):
    Environment.from_env(name='app', app_path=tmp_path)


def test_a_service_registers(tmp_path):
  (tmp_path / 'config.yaml').write_text(
    "boxes:\n  templates: {nas: {service: true}}\n  s1: {template: nas}\n  s9: {}\n", encoding='utf-8')
  Environment.from_env(name='app', app_path=tmp_path)
  assert list(State.services) == ['s1'] and State.services['s1'] is State.boxes['s1']
# endregion
