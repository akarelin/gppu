<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/icons.py 5959a41dfc99bc120ba5d876045749c9453161a3 -->
`gppu.tui.icons` gives every gppu terminal UI one shared set of symbols for task state, connectivity, warnings, and spinners, so applications do not each choose their own check mark or animation characters.

The module has two families. `STATE_GLYPHS` maps a state key, such as `running`, `ok`, `fail`, `reachable`, or `warn`, to a `Glyph`. A `Glyph` is a named tuple with three fields: the one-character symbol, a Rich color name, and the SGR parameters for plain ANSI output. `glyph_rich()` returns a state key as a Rich markup string, and `glyph_ansi()` returns it as a raw ANSI string. An unknown key renders as a dim `?` in Rich output and as `?` in ANSI output instead of raising an error. The keys cover three groups: task lifecycle (`pending`, `queued`, `running`, `ok`, `fail`, `canceled`, `skipped`), connectivity (`reachable`, `unreachable`, `probing`), and notes (`warn`, `info`, `error`). New states are added to the dictionary as they are needed.

`SPINNERS` maps a name to a string of animation frames: `dots`, `line`, `arc`, `triangle`, or `pulse`. `spinner_frames()` returns the frames for a name and falls back to `dots` when the name is unknown. The `dots` set is the one `gppu.tui.SpinnerIndicator` already uses for background processes. The other sets are variants for specific layouts: `line` for narrow columns, `arc` for better visibility on dark terminals, `triangle` for a single focal indicator, and `pulse` for minimal motion in each row.

## Usage

A program imports the glyphs and frame sets from the module and uses them directly:

```python
from gppu.tui.icons import STATE_GLYPHS, glyph_rich, SPINNERS

label = glyph_rich('ok') + ' pulled'
widget.spinner_frames = SPINNERS['arc']
```
