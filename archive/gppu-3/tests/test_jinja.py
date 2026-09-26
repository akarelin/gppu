import pytest

from jinja2 import StrictUndefined, UndefinedError
from gppu import JinjaEnvironment, TemplateSet, dict_from_yml, jinja_template


def test_native_command_keeps_payload_types():
  result = jinja_template("{{ {'state': cmd, 'brightness': brightness, 'mode': mode} }}",
                          cmd='on', brightness=0, mode=None)
  assert result == {'state': 'on', 'brightness': 0, 'mode': None}
  assert type(result['brightness']) is int


def test_jinja_statement_and_filter():
  assert jinja_template('{% set value = name | upper %}{{ value }}', name='kitchen') == 'KITCHEN'
  assert jinja_template('{{ value | safe_int }}', value='12') == 12


def test_null_false_and_list_are_native():
  assert jinja_template('{{ none }}') is None
  assert jinja_template('{{ false }}') is False
  assert jinja_template('{{ [0, false, none] }}') == [0, False, None]


def test_missing_input_is_an_error():
  with pytest.raises(UndefinedError): jinja_template('{{ missing }}')
  with pytest.raises(UndefinedError): jinja_template('{{ missing + 1 }}')
  assert JinjaEnvironment().undefined is StrictUndefined


def test_plain_text_is_not_python_code():
  assert jinja_template('return 1 + 2') == 'return 1 + 2'


def test_template_can_be_a_context_key():
  assert jinja_template('{{ template }}', template='kitchen') == 'kitchen'


def test_document_renders_text_not_native_values(tmp_path):
  (tmp_path / 'macros.j2').write_text(
    "{% macro row(name) %}\n  {{ name }}: {{ name | upper }}\n{%- endmacro %}\n", encoding='utf-8')
  (tmp_path / 'config.yaml.j2').write_text(
    "{% import 'macros.j2' as m %}\n"
    "{% set facts = 'facts.yaml' | from_yaml %}\n"
    "hosts:\n"
    "{% for name in facts.names %}\n"
    "{{ m.row(name) }}\n"
    "{% endfor %}\n", encoding='utf-8')
  (tmp_path / 'facts.yaml').write_text("names: [seven, trix]\n", encoding='utf-8')

  assert dict_from_yml(tmp_path / 'config.yaml.j2') == {
    'hosts': {'seven': 'SEVEN', 'trix': 'TRIX'}}


def test_document_include_resolves_beside_the_template(tmp_path):
  (tmp_path / 'part.j2').write_text("count: {{ 1 + 1 }}\n", encoding='utf-8')
  (tmp_path / 'main.yaml.j2').write_text("{% include 'part.j2' %}", encoding='utf-8')
  assert dict_from_yml(tmp_path / 'main.yaml.j2') == {'count': 2}


def test_missing_document_input_is_an_error(tmp_path):
  (tmp_path / 'main.yaml.j2').write_text("key: {{ missing }}\n", encoding='utf-8')
  with pytest.raises(UndefinedError): dict_from_yml(tmp_path / 'main.yaml.j2')


def template_set():
  return TemplateSet(
    macros="{% macro address(name, addr='') %}{{ addr or name }}.c.karel.in{% endmacro %}",
    generators={'host': "{{ {'hostname': address(name, addr), 'shell': platforms[os].shell} }}"},
    templates={'server': {'generator': 'host', 'os': 'debian', 'addr': '', 'repos': ['RAN']}},
    platforms={'debian': {'shell': 'bash'}},
  )


def test_row_takes_its_template_and_what_the_generator_computes():
  resolved = template_set().resolve({'name': 'seven', 'addr': '7', 'template': 'server'})
  assert resolved['hostname'] == '7.c.karel.in'   # computed
  assert resolved['repos'] == ['RAN']             # the template's
  assert resolved['addr'] == '7'                  # the row's, over the template's
  assert 'template' not in resolved and 'generator' not in resolved


def test_a_row_beats_the_template_and_the_generator():
  resolved = template_set().resolve({'name': 'five', 'template': 'server', 'repos': ['RAN', 'CRAP'],
                                     'hostname': 'five.example'})
  assert resolved['repos'] == ['RAN', 'CRAP']
  assert resolved['hostname'] == 'five.example'


def test_null_un_inherits_a_key_the_template_carries():
  assert 'repos' not in template_set().resolve({'name': 'bare', 'template': 'server', 'repos': None})


def test_resolve_all_takes_a_list_or_a_mapping():
  rows = [{'name': 'seven', 'template': 'server'}, {'name': 'five', 'template': 'server'}]
  assert [r['hostname'] for r in template_set().resolve_all(rows)] == ['seven.c.karel.in', 'five.c.karel.in']
  keyed = {'seven': {'name': 'seven', 'template': 'server'}}
  assert template_set().resolve_all(keyed)['seven']['hostname'] == 'seven.c.karel.in'


def test_a_generator_must_return_an_object():
  broken = TemplateSet(generators={'text': 'just words'}, templates={'t': {'generator': 'text'}})
  with pytest.raises(TypeError): broken.resolve({'template': 't'})


def test_an_unknown_generator_is_an_error():
  with pytest.raises(KeyError): TemplateSet(templates={'t': {'generator': 'missing'}}).resolve({'template': 't'})


def test_behavior_rewrites_what_the_row_itself_carries():
  """A generator cannot touch a key the row carries; a behavior runs after the merge."""
  resolved = TemplateSet(
    generators={'sets': "{{ {'services': services | map('upper') | list} }}"},
    templates={'host': {'behavior': 'sets'}},
  ).resolve({'template': 'host', 'services': ['docker', 'nginx']})
  assert resolved['services'] == ['DOCKER', 'NGINX']
