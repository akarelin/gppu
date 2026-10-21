<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/viz/heatmap.py a2e7eb9c7bd391f3c2c6e89ddb736285672166de -->
The `gppu.tui.viz.heatmap` module draws a GitHub-style activity heatmap of daily counts, for a terminal or a Textual screen. You pass a mapping of dates to counts, and it returns a grid of colored density blocks covering the most recent days.

## How the pieces work together

`render_heatmap_lines` does the drawing. It returns a list of Rich-markup strings, so the lines can go into a `RichLog` or a Rich `Console`. The grid has seven rows, one per weekday from Mon to Sun, and one column per week. The first column starts on a Monday, and cells before the first day of the range stay blank. Each day's count maps to one glyph and color: 0 is `·` in bright black, up to 2 is `░` in green, up to 8 is `▒` in yellow, up to 24 is `▓` in orange, and anything higher is `█` in red. A title and a legend line sit above the grid, and a totals line below it gives the total count, labeled with `unit` (default `session-days`), and the number of active days. The range ends today, using the local date, and reaches back `days` days (default 90). Passing `title=None` removes the title and legend lines.

The caller supplies the counts. Days missing from the dict count as zero, so the dict only needs days with activity.

`counts_from_timestamps` builds that dict from `datetime` objects or ISO-8601 strings. A trailing `Z` is read as UTC. Strings that fail to parse, and values that are neither strings nor datetimes, are skipped without an error. Each timestamp counts on the date it carries.

`Heatmap` is a Textual `Static` widget that wraps the same output so it fits into any layout. It takes the counts and the same `days`, `title` and `unit` options, and `set_counts` re-renders it in place. The class exists only when Textual is importable. Otherwise the name `Heatmap` is `None`.

## Usage

```python
from datetime import date

from rich.console import Console

from gppu.tui.viz.heatmap import render_heatmap_lines

console = Console()
counts = {date(2026, 10, 20): 5, date(2026, 10, 21): 12}
for line in render_heatmap_lines(counts, days=30, unit='commits'):
    console.print(line)
```
