"""Tests for _py_compile / py_evaluate / py_generate / py_register — the restricted
template engine: Evaluator (state calculation from a data dict) and Generator
(config -> .data object), with named templates and dict-union inheritance."""
import types

import pytest

from gppu import py_evaluate, py_generate, py_register, py_template
from gppu.gppu import _py_compile, _py_templates


@pytest.fixture
def templates():
    """Register templates for a test; restore the registry afterwards."""
    saved = dict(_py_templates)

    def register(**kw):
        for name, src in kw.items():
            py_register(name, src)

    yield register
    _py_templates.clear()
    _py_templates.update(saved)


class TestEvalExprConfigPatterns:
    """The exact expression shapes used in Creekview/*.yaml state_templates."""

    def test_power_ternary_on(self):
        assert py_evaluate("'on' if (this.power or 0) > 10 else 'off'", this=_obj(power=42)) == 'on'

    def test_power_ternary_off(self):
        assert py_evaluate("'on' if (this.power or 0) > 10 else 'off'", this=_obj(power=5)) == 'off'

    def test_power_ternary_none_seeded(self):
        # this.power seeded to None before first reading -> (None or 0) -> 0
        assert py_evaluate("'on' if (this.power or 0) > 10 else 'off'", this=_obj(power=None)) == 'off'

    def test_power_or_zero_value(self):
        assert py_evaluate("this.power or 0", this=_obj(power=123.4)) == 123.4

    def test_power_or_zero_none(self):
        assert py_evaluate("this.power or 0", this=_obj(power=None)) == 0

    def test_states_equality_ternary(self):
        states = lambda eid: 'on' if eid == 'binary_sensor.garage' else 'off'
        assert py_evaluate("'open' if states('binary_sensor.garage') == 'on' else 'closed'", states=states) == 'open'

    def test_states_inequality_bool(self):
        states = lambda eid: 'off'
        assert py_evaluate('states("btn.aob_7") != "on"', states=states) is True

    def test_brace_wrapper_stripped(self):
        assert py_evaluate("{{ this.power or 0 }}", this=_obj(power=None)) == 0


class TestEvalExprBuiltins:
    def test_default_replaces_none(self):
        assert py_evaluate("default(this.power, 0)", this=_obj(power=None)) == 0

    def test_default_keeps_value(self):
        assert py_evaluate("default(this.power, 0)", this=_obj(power=7)) == 7

    def test_safe_float(self):
        assert py_evaluate("safe_float('3.5')") == 3.5

    def test_data_overrides_builtin(self):
        assert py_evaluate("default", default='data-wins') == 'data-wins'


class TestDictUnion:
    """`|` is the inheritance operator: base | instance | overrides, rightmost wins."""

    def test_union(self):
        assert py_evaluate("{'a': 1} | {'b': 2}") == {'a': 1, 'b': 2}

    def test_rightmost_wins(self):
        assert py_evaluate("{'a': 1, 'b': 1} | {'b': 2}") == {'a': 1, 'b': 2}

    def test_union_with_default(self):
        assert py_evaluate("{'on_level': 127} | default(flags, {})", flags={'backlight': 1}) == {'on_level': 127, 'backlight': 1}

    def test_augmented_union_in_generator(self):
        assert py_generate("d = {'a': 1}\nd |= {'b': 2}\nreturn d") == {'a': 1, 'b': 2}


class TestNamedTemplates:
    def test_run_by_name(self, templates):
        templates(t_answer="6 * 7")
        assert py_evaluate("t_answer") == 42

    def test_bare_name_reference(self, templates):
        templates(t_dimmer="{'class': 'IDevice', 'domain': 'light'}",
                  t_i1="{'instance': 'i1'}",
                  t_dimmer_i1="t_dimmer | t_i1")
        assert py_evaluate("t_dimmer_i1") == {'class': 'IDevice', 'domain': 'light', 'instance': 'i1'}

    def test_referenced_template_sees_same_data(self, templates):
        templates(t_core="{'eid': domain + '.' + name}",
                  t_light="t_core | {'schema': 'json'}")
        assert py_evaluate("t_light", domain='light', name='pendant') == {'eid': 'light.pendant', 'schema': 'json'}

    def test_data_wins_over_template(self, templates):
        templates(t_base="{'a': 1}")
        assert py_evaluate("t_base | {'b': 2}", t_base={'a': 'data'}) == {'a': 'data', 'b': 2}

    def test_generator_body_by_name(self, templates):
        templates(t_gen="d = {'name': name}\nif name == 'x': d['marked'] = True\nreturn d")
        assert py_generate("t_gen", name='x') == {'name': 'x', 'marked': True}

    def test_cycle_raises(self, templates):
        templates(t_a="t_b | {}", t_b="t_a | {}")
        with pytest.raises(ValueError, match='cycle'):
            py_evaluate("t_a")

    def test_py_template_lookup(self, templates):
        templates(t_x="1 + 1")
        assert isinstance(py_template('t_x'), types.CodeType)
        assert py_template('t_missing') is None

    def test_reregister_replaces(self, templates):
        templates(t_x="1")
        templates(t_x="2")
        assert py_evaluate("t_x") == 2


class TestCompileCaching:
    def test_returns_code_object(self):
        assert isinstance(_py_compile("1 + 1"), types.CodeType)

    def test_cache_returns_same_object(self):
        # Same source (incl. {{ }} wrapper variants) -> same cached code object.
        assert _py_compile("2 * 21 + 0") is _py_compile("{{ 2 * 21 + 0 }}")

    def test_precompiled_code_evaluates(self):
        code = _py_compile("a + b")
        assert py_evaluate(code, a=2, b=3) == 5


class TestSecurityBoundary:
    @pytest.mark.parametrize("expr", [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__",
        "this.__class__",
        "[x for x in range(3)]",          # comprehension
        "(lambda: 1)()",                  # lambda
        "import os",                      # statement body -> Import node rejected
        "a := 5",                         # walrus
    ])
    def test_disallowed_constructs_rejected(self, expr):
        with pytest.raises(ValueError):
            _py_compile(expr)

    def test_real_builtins_unavailable(self):
        # open() is a real builtin, not in _EXPR_BUILTINS -> NameError at eval
        with pytest.raises(NameError):
            py_evaluate("open('/etc/passwd')")

    def test_unknown_name_raises(self):
        with pytest.raises(NameError):
            py_evaluate("nonexistent_helper(1)")


class _obj:
    """Minimal stand-in for a Y2 entity exposing channel attrs as `this.<name>`."""
    def __init__(self, **kw):
        self.__dict__.update(kw)
