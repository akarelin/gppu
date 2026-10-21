<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/progress.py 54c1f617fc60abe8be82e8c6780e816fab9b498f -->
`gppu.tui.progress` reports progress for long-running TUI and CLI operations as a strip of markers, written one line at a time through a log callable. A strip is written every N items or every T seconds, whichever comes first, and a closing line ends the run.

## How the classes work together

Both trackers share a base class that batches output. `TickProgress` writes a dim `·` for each noted item and does not classify items. `MarkerProgress` writes one colored glyph per item. Its `classify` function maps each item passed to `note` to a `Marker`, and a falsy result counts as the `unknown` marker. A `Marker` is a frozen dataclass with a key, a label, a symbol, a Rich color name, and an ANSI SGR code. `MarkerProgress` counts each category. Its `summary()` returns a sentence listing the counts in category order, with the unknown count last. The `noun` argument names the items in that sentence.

The `rich` flag on each tracker selects the markup. With `rich=True`, the default, output uses Rich markup for a log that renders it, such as Textual's RichLog with markup enabled. With `rich=False`, output uses raw ANSI escapes for a plain terminal. The helpers `marker_rich` and `marker_ansi` format one marker's symbol in either mode. `legend_rich` and `legend_ansi` build a one-line key for a tuple of markers.

Batching is checked only when an item is noted. A strip is written once the pending count reaches `tick_every`, or once `tick_seconds` have passed since the last write. A quiet period therefore produces no output until the next item arrives or `close()` runs. `close()` writes any pending items and then the closing line. A tracker that noted nothing writes nothing, so the caller does not need to check whether anything was found. `TickProgress` closes with `discovered N items`. `MarkerProgress` closes with its summary.

## Usage

Create a tracker with a log callable, call `note` for each item, and call `close` when the loop ends:

```python
from gppu.tui.progress import TickProgress

prog = TickProgress(print, rich=False)
for item in items:
    prog.note()
prog.close()
```
