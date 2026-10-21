"""Tests of dict_from_yml's bare !include merge and .j2 rendering, both gone from dict_from_yml."""

# from tests/test_yaml.py (inside its test class)
    def test_bare_include_merges_into_document(self, tmp_path):
        (tmp_path / "hosts.yaml").write_text("hosts:\n  alex-pc: {}\n")
        (tmp_path / "odds.yaml").write_text("vars:\n  endpoint: https://otel\n")
        main = tmp_path / "main.yaml"
        main.write_text("!include hosts.yaml\n\nharness: !include odds.yaml\n\n!include odds.yaml\n")
        result = dict_from_yml(str(main))
        assert result["hosts"] == {"alex-pc": {}}
        assert result["harness"] == {"vars": {"endpoint": "https://otel"}}
        assert result["vars"] == {"endpoint": "https://otel"}

    def test_bare_include_nests(self, tmp_path):
        (tmp_path / "leaf.yaml").write_text("leaf: 1\n")
        (tmp_path / "branch.yaml").write_text("!include leaf.yaml\nbranch: 2\n")
        main = tmp_path / "main.yaml"
        main.write_text("!include branch.yaml\nroot: 3\n")
        result = dict_from_yml(str(main))
        assert result == {"leaf": 1, "branch": 2, "root": 3}


# from tests/test_jinja.py
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


