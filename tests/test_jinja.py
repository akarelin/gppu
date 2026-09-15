import pytest

from jinja2 import StrictUndefined, UndefinedError
from gppu import JinjaEnvironment, dict_from_yml, jinja_template


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
