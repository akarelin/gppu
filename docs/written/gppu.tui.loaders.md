<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/loaders.py d23ab48b29eba75c0d9ada27db39d1577add7e8e -->
`gppu.tui.loaders` runs slow data fetches in a background thread for Textual apps, so the interface stays responsive while data loads. It removes the worker method and table-population code that each table would otherwise need.

The module's one class is `LoaderMixin`, which adds two methods to a Textual `App` or `Screen`. It needs nothing beyond the host's `query_one`, `call_from_thread` and `run_worker`.

`load_into_table` fills a `DataTable`. It runs `fetch` in a worker thread, then on the main thread clears the table (unless `clear_first` is false) and adds one row per fetched item. `row_fn` turns each item into a sequence of cell values, or into a `(cells, key)` tuple to set the row key. `row_fn` runs on the main thread during population, so it should only build cells. The widget named by `status_id` shows `status_busy` while the fetch runs and `status_done` afterward. `status_done` can be a string or a function of the fetched rows. An optional `on_done` callback receives the rows after the table is populated.

`load_async` follows the same pattern without a table. It runs `fetch` in a worker thread and passes the result to `on_done` on the main thread, which suits widgets such as a `RichLog`, a `Tree`, or a custom widget. Its `status_done` is a plain string.

Both methods start the work with `run_worker(thread=True)` under the name given by `name`, which defaults to `loader` and `loader-async`. A failure in `fetch` is logged with `Error` and shown on the status line as `Error: <e>`. In `load_into_table`, a missing table is logged with `Debug` and the load stops, and a missing status widget is skipped. An exception in `on_done` is logged with `Error`. `load_async` also shows it on the status line, while `load_into_table` only logs it.

A program calls the mixin from its own app class:

```python
from gppu.tui import LoaderMixin

class MyApp(LoaderMixin, TUIApp):
    def on_mount(self):
        self.load_into_table(
            table_id='#sessions-table',
            fetch=lambda: api_get_paginated('/api/traces', max_pages=10),
            row_fn=lambda t: (
                ('local', t['project'], t['date'], t['name']),
                t['id'],
            ),
            status_id='#status-bar',
            status_busy='Loading sessions…',
            status_done=lambda rows: f'✓ {len(rows)} loaded',
        )
```
