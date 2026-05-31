"""Tests for compile_expr / eval_expr — the restricted single-expression
evaluator that replaces sandboxed Jinja for Y2 `state_template` / `enabled_when`."""
import pytest
from gppu import compile_expr, eval_expr


class TestEvalExprConfigPatterns:
    """The exact expression shapes used in Creekview/*.yaml state_templates."""

    def test_power_ternary_on(self):
        assert eval_expr("'on' if (this.power or 0) > 10 else 'off'", this=_obj(power=42)) == 'on'

    def test_power_ternary_off(self):
        assert eval_expr("'on' if (this.power or 0) > 10 else 'off'", this=_obj(power=5)) == 'off'

    def test_power_ternary_none_seeded(self):
        # this.power seeded to None before first reading -> (None or 0) -> 0
        assert eval_expr("'on' if (this.power or 0) > 10 else 'off'", this=_obj(power=None)) == 'off'

    def test_power_or_zero_value(self):
        assert eval_expr("this.power or 0", this=_obj(power=123.4)) == 123.4

    def test_power_or_zero_none(self):
        assert eval_expr("this.power or 0", this=_obj(power=None)) == 0

    def test_states_equality_ternary(self):
        states = lambda eid: 'on' if eid == 'binary_sensor.garage' else 'off'
        assert eval_expr("'open' if states('binary_sensor.garage') == 'on' else 'closed'", states=states) == 'open'

    def test_states_inequality_bool(self):
        states = lambda eid: 'off'
        assert eval_expr('states("btn.aob_7") != "on"', states=states) is True

    def test_brace_wrapper_stripped(self):
        assert eval_expr("{{ this.power or 0 }}", this=_obj(power=None)) == 0


class TestEvalExprBuiltins:
    def test_default_replaces_none(self):
        assert eval_expr("default(this.power, 0)", this=_obj(power=None)) == 0

    def test_default_keeps_value(self):
        assert eval_expr("default(this.power, 0)", this=_obj(power=7)) == 7

    def test_safe_float(self):
        assert eval_expr("safe_float('3.5')") == 3.5

    def test_ctx_overrides_builtin(self):
        assert eval_expr("default", default='ctx-wins') == 'ctx-wins'


class TestCompileExprCaching:
    def test_returns_code_object(self):
        import types
        assert isinstance(compile_expr("1 + 1"), types.CodeType)

    def test_cache_returns_same_object(self):
        # Same source (incl. {{ }} wrapper variants) -> same cached code object.
        assert compile_expr("2 * 21 + 0") is compile_expr("{{ 2 * 21 + 0 }}")

    def test_precompiled_code_evaluates(self):
        code = compile_expr("a + b")
        assert eval_expr(code, a=2, b=3) == 5


class TestSecurityBoundary:
    @pytest.mark.parametrize("expr", [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__",
        "this.__class__",
        "[x for x in range(3)]",          # comprehension
        "(lambda: 1)()",                  # lambda
        "import os",                      # statement -> SyntaxError -> ValueError
        "a := 5",                         # walrus
    ])
    def test_disallowed_constructs_rejected(self, expr):
        with pytest.raises(ValueError):
            compile_expr(expr)

    def test_real_builtins_unavailable(self):
        # open() is a real builtin, not in _EXPR_BUILTINS -> NameError at eval
        with pytest.raises(NameError):
            eval_expr("open('/etc/passwd')")

    def test_unknown_name_raises(self):
        with pytest.raises(NameError):
            eval_expr("nonexistent_helper(1)")


class _obj:
    """Minimal stand-in for a Y2 entity exposing channel attrs as `this.<name>`."""
    def __init__(self, **kw):
        self.__dict__.update(kw)
