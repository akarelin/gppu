<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/viz/__init__.py 32135849edd63f2aa54540d8df9b0add09459f45 -->
The source you gave supports only the opening paragraph and the export list. The module's relationships and the example need `heatmap.py`, which you excluded, so the draft below is partial.

```markdown
`gppu.tui.viz` provides visualization widgets for gppu TUI apps.

The package exports two names, `Heatmap` and `render_heatmap_lines`, both defined in its `heatmap` submodule. Import them from the package: `from gppu.tui.viz import Heatmap, render_heatmap_lines`.
```

Word count: 49 of 400. The sentence on how `Heatmap` and `render_heatmap_lines` work together is missing, because the source doesn't say. The example is missing too, because the source has no docstrings or signatures beyond the module docstring.

To finish the page, I need `gppu/tui/viz/heatmap.py` added to this session. Once I have it, I will write the relationship prose and the example from its docstrings and signatures, and keep the draft within the 400-word limit.
