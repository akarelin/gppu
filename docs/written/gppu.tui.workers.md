<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/workers.py 7c6d42edb06794c875a1dda018e5c19f12ecdc63 -->
`gppu.tui.workers` shows the progress of several concurrent tasks in a Textual app. Each task gets one line with a spinner, a state glyph, a label and a detail text, and a footer counts the tasks in each state.

## How the parts work together

`WorkerState` is the plain data record for one task: its key, label, state, detail text and optional numeric counters. `WorkerRow` is the widget that draws one `WorkerState` as a single line, and it runs its spinner only while the state is `running`. `WorkerPool` is the container. It holds one `WorkerState` and one `WorkerRow` per key, stacks the rows vertically, and keeps the aggregate footer current.

States are the keys of `STATE_GLYPHS` in `gppu.tui.icons`: pending, queued, running, ok, fail, canceled and skipped. The state sets the row's glyph. The footer lists only the states that occur, in a fixed order, followed by the total.

The pool does not schedule work. An orchestrator, such as a `ThreadPoolExecutor` or a `@work(thread=True)` block, calls `WorkerPool.mark` to move a task to a new state with a detail string and optional counters. `mark` redraws that row and the footer. It must run on the main thread; from a worker thread, pass it through `app.call_from_thread`. An unknown key is added as a new row instead of raising an error. `add_worker` adds a row after mount and does nothing if the key already exists. `get` returns a task's current state, or `None`.

Counters are stored on the `WorkerState`, but `WorkerRow` does not draw them. The row shows only the glyph, label and detail.

## Using it

A host-parallel pull seeds one row per host and reports each host through `mark`:

```python
pool = WorkerPool(id='hosts', workers=[ws.name for ws in hosts])
yield pool
...
def on_pull_start(host): pool.mark(host, 'running', 'pulling')
def on_pull_done(host, n): pool.mark(host, 'ok', f'pulled {n}')
def on_pull_fail(host, e): pool.mark(host, 'fail', str(e)[:40])
```
