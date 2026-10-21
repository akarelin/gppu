"""Env and State: the shared configuration constructed at startup."""
from pathlib import Path

import pytest

from gppu import Env, State, TemplateSet
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
    monkeypatch.setattr(Env, 'host', host)
    monkeypatch.setattr(Env, 'platform', platform)
    Env.from_env(name='locations', app_path=EXAMPLE)
    State.reset()   # the same configuration seen from another host
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


def test_a_named_template_renders_later_with_what_a_rule_knows():
  templates = TemplateSet(named={'uri_templates': {'box': 'smb://{{ host }}/{{ share }}/{{ path }}'}},
                          templates={'resource': {'refs': {'uri': 'uri_templates'}}})
  assert templates.resolve({'uid': 'smb', 'template': 'resource', 'uri': 'box'})['uri'] == 'box'   # data until rendered
  assert templates.render_template('box', host='s1.karel.in', share='SD', path='x') == 'smb://s1.karel.in/SD/x'
  with pytest.raises(KeyError, match="smb: uri names 'nope', which is not in uri_templates"):
    templates.resolve({'uid': 'smb', 'template': 'resource', 'uri': 'nope'})


def test_refs_merge_across_stacked_templates():
  templates = TemplateSet(templates={'a': {'refs': {'x': 'xs'}}, 'b': {'refs': {'y': 'ys'}}}, xs={'1': {}}, ys={'2': {}})
  with pytest.raises(KeyError, match="y names '3'"):
    templates.resolve({'uid': 'r', 'template': ['a', 'b'], 'x': '1', 'y': '3'})
# endregion


# region Startup: State, the tables constructed while the configuration loads
def test_every_table_is_constructed_and_registered(on):
  on('alex-laptop', 'windows')
  assert set(State.tables) == {'resources', 'connections', 'hosts', 'locations', 'entities', 'sources'}
  assert State.resources['smb']['class'] == 'SmbShare' and State.resources['smb']['uri'] == 'box'
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
  assert State.locations['sd-agents']['local'] == '/mnt/S1/SD.agents'
  assert State.locations['public']['local'] == '/mnt/Public'
  assert 'local' not in State.locations['yellow-config']              # seven is not connected to yellow
  assert 'local' not in State.locations['obsidian']
  on('alex-mac', 'macos')
  assert State.locations['public']['local'] == '/Volumes/Public'
  on('alex-pc', 'wsl')
  assert State.locations['sd-lake']['local'] == '/mnt/d/SD.Lake'
  on('trix', 'debian')
  assert State.locations['sd-agents']['local'] == '/home/alex/SD.agents'   # the row's own place for one host
  on('iot', 'debian')
  assert State.locations['yellow-config']['local'] == '/mnt/yellow/config'


def test_a_namespace_is_its_own_scheme_and_what_is_in_it_follows(on):
  on('alex-laptop', 'windows')
  assert State.locations['lake']['canonical'] == 'lake://' and State.locations['lake']['local'] == 'D:/TextLake'
  assert State.locations['karelin-contacts']['canonical'] == 'm365://karelin/alex/contacts'   # served at the root of the service
  assert State.locations['karelin-contacts']['mirrors'] == ['lake://M365/karelin/users/alex@karelin.com/contacts']
  assert State.locations['karelin-contact-photos']['canonical'] == 'm365://karelin/alex/onedrive/Documents/Contact Photos'


def test_a_location_inside_another_is_where_that_one_is(on):
  on('alex-laptop', 'windows')
  assert State.locations['karelin-contacts']['inside'] == 'lake'
  assert State.locations['karelin-contacts']['local'] == 'D:/TextLake/M365/karelin/users/alex@karelin.com/contacts'
  on('trix', 'debian')
  assert State.locations['karelin-contacts']['local'] == '/mnt/S1/Lake/text/M365/karelin/users/alex@karelin.com/contacts'
  assert 'local' not in State.locations['karelin-contact-photos']    # trix has no OneDrive client


def test_a_source_is_a_location_and_what_is_in_it(on):
  on('alex-laptop', 'windows')
  source = State.sources['karelin-contacts']
  assert source['address'] == 'm365://karelin/alex/contacts' and source['provides'] == 'contacts'
  assert source['local'] == 'D:/TextLake/M365/karelin/users/alex@karelin.com/contacts'
  assert State.sources['karelin-contact-photos']['local'] == 'D:/OneDrive - Karelin/Contact Photos'


def test_a_configuration_without_tables_has_no_rules():
  Env.from_dict({'a': {'b': 1}})
  assert Env.glob('a/b') == 1
  with pytest.raises(AttributeError): Env.locations


def test_a_dangling_reference_fails_the_load(tmp_path):
  (tmp_path / 'config.yaml').write_text(
    "connections:\n  templates: {box: {}}\n  s1: {template: box}\n"
    "locations:\n  templates:\n    location: {refs: {'smb/*': connections}}\n"
    "  lake: {template: location, smb/s3: Lake}\n", encoding='utf-8')
  Env.from_env(name='app', app_path=tmp_path)
  with pytest.raises(KeyError, match="lake: smb/\\* names 's3', which is not in connections"):
    State.tables


def test_a_service_registers(tmp_path):
  (tmp_path / 'config.yaml').write_text(
    "boxes:\n  templates: {nas: {service: true}}\n  s1: {template: nas}\n  s9: {}\n", encoding='utf-8')
  Env.from_env(name='app', app_path=tmp_path)
  assert list(State.services) == ['s1'] and State.services['s1'] is State.boxes['s1']
# endregion


# region Runtime: code calls a table's macros and renders its named templates
def test_code_asks_a_place_for_any_host(on):
  on('seven', 'debian')
  assert State.locations['sd-lake']['local'] == '/mnt/S1/SD.Lake'
  assert State.locations['public']['local'] == '/mnt/Public' and Env.locations.place('public', 'alex-mac', 'macos') == '/Volumes/Public'
  assert 'local' not in State.locations['yellow-config']              # seven is not connected to yellow
  assert 'local' not in State.locations['obsidian']
  assert Env.locations.place('sd-lake', 'alex-pc', 'wsl') == '/mnt/d/SD.Lake'
  assert Env.locations.place('sd-agents', 'trix', 'debian') == '/home/alex/SD.agents'   # the row's own place for one host
  assert Env.locations.place('sd-agents', 'seven', 'debian') == '/mnt/S1/SD.agents'
  assert Env.locations.place('yellow-config', 'seven', 'debian') is None       # seven is not connected to yellow
  assert Env.locations.place('yellow-config', 'iot', 'debian') == '/mnt/yellow/config'
  assert list(Env.locations.on_host('alex-pc')) == ['profile', 'dev', 'sd', 'sd-lake', 'sd-agents', 'onedrive', 'ran',
                                                            'obsidian', 'lake', 'karelin-contacts', 'karelin-contact-photos']


def test_an_address_resolves_to_a_path_on_this_host(on):
  on('alex-laptop', 'windows')
  assert Env.locations.local_of('sd://SD.Lake/inbox') == 'D:/SD.Lake/inbox'
  assert Env.locations.local_of('smb://s1.karel.in/Public/x') is None
  assert Env.locations.folder('sd-lake', 'inbox') == 'D:/SD.Lake/inbox'
  assert Env.locations.local_of('smb://s1.karel.in/Public/x', 'seven', 'debian') == '/mnt/Public/x'
  assert Env.locations.uri('sd-lake', 'sd') == 'sd://SD.Lake' and Env.locations.uri('public', 'sd') is None


def test_code_asks_where_a_location_inside_another_is(on):
  on('alex-laptop', 'windows')
  assert State.locations['karelin-contacts']['inside'] == 'lake'
  assert Env.locations.place('karelin-contacts') == 'D:/TextLake/M365/karelin/users/alex@karelin.com/contacts'
  assert Env.locations.place('karelin-contacts', 'trix', 'debian') == \
         '/mnt/S1/Lake/text/M365/karelin/users/alex@karelin.com/contacts'
  assert Env.locations.place('karelin-contact-photos', 'trix', 'debian') is None    # trix has no OneDrive client


def test_the_same_address_is_a_path_on_the_workstation_and_on_the_server(on):
  on('alex-laptop', 'windows')
  for address, laptop, trix in (
    ('lake://Person/aaron-mendes.md', 'D:/TextLake/Person/aaron-mendes.md', '/mnt/S1/Lake/text/Person/aaron-mendes.md'),
    ('m365://karelin/alex/contacts/default/x.json',
     'D:/TextLake/M365/karelin/users/alex@karelin.com/contacts/default/x.json',
     '/mnt/S1/Lake/text/M365/karelin/users/alex@karelin.com/contacts/default/x.json')):
    assert Env.locations.local_of(address) == laptop
    assert Env.locations.local_of(address, 'trix', 'debian') == trix


def test_an_entity_kind_names_the_grammars_of_its_permalink_and_document(on):
  on('alex-laptop', 'windows')
  rules, person = Env.entities, State.entities['person'].data
  assert rules.render_template(person['permalink'], **person, slug='aaron-mendes') == 'person://aaron-mendes'
  assert rules.render_template(person['document'], **person, slug='aaron-mendes') == 'lake://Person/aaron-mendes.md'
  assert rules.kind_of({'companyName': 'A&Z', 'displayName': 'A&Z'}) == 'company'
  assert rules.kind_of({'givenName': 'Aaron', 'companyName': 'Gameplan'}) == 'person'
  assert rules.identity_of({'emailAddresses': [{'address': 'A@B.com'}]}) == 'a@b.com'
  assert rules.slug_for({'displayName': 'A&Z Air Conditioning'}) == 'a-z-air-conditioning'


def test_a_command_runs_on_a_host_as_its_platform_says(on):
  on('alex-laptop', 'windows')
  assert Env.hosts.ssh('seven', 'debian') == ['ssh', '-p', '22', 'alex@7.c.karel.in', 'bash', '-s']
  assert Env.hosts.ssh('alex-pc', 'windows')[:4] == ['ssh', '-p', '22222', 'administrator@alex-pc.c.karel.in']
# endregion
