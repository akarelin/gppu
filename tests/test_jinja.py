import pytest

from jinja2 import StrictUndefined, UndefinedError
from gppu import JinjaEnvironment, jinja_template


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
