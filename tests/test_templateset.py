"""TemplateSet: a row resolved through its templates."""
import pytest

from gppu import TemplateSet


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
