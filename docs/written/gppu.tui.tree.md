<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/tree.py 4e978d64ab14256acd4a95a6d8455a49c8a83c3a -->
`gppu.tui.tree` gives a Textual app a browse-and-select tree over a hierarchical data source, such as a local filesystem, a Google Drive, or an S3 bucket. It handles lazy expansion, placeholder nodes, and the selection message, so the app supplies only the data.

## How the pieces work together

`TreeAdapter` is the protocol the caller implements for its data source. `root()` returns one seed `TreeEntry`, and `children()` returns the entries under a container entry. Each `TreeEntry` has a stable `id` that its adapter understands, a `label`, an `is_container` flag, and a free-form `meta` dictionary for values such as sizes, modification times, or MIME types.

`TreeBrowser` is a Textual `Tree` built on an adapter. By default it is lazy: each container gets a placeholder child labelled "Loading…", which is replaced by a call to `children()` the first time the node expands. With `lazy=False`, the browser fills the whole tree at mount. A container with no children shows "(empty)". When the user presses Enter on a node, the browser posts `TreeBrowser.EntrySelected`, which carries the `TreeEntry` and its node, so the app can react without subclassing.

Two adapters are bundled:

- `FilesystemAdapter` walks a local directory. It expands and normalizes `root_path` once, when it is constructed. It hides dotfiles unless `show_hidden` is set, and it stops recursion at `max_depth` when that is set. Directories are listed before files, and directory labels end in `/`.
- `GDriveAdapter` lists Google Drive folders. The caller passes an already-authenticated Drive `service` object, so gppu carries no Google SDK dependency. It pages through each folder's listing, and if a Drive call fails, it ends that listing with the folders gathered so far.

Adapter methods run on the main thread. Wrap slow I/O in the caller's `LoaderMixin.load_async`.

## Usage

```python
from gppu.tui import TreeBrowser, FilesystemAdapter

class MyApp(TUIApp):
    def compose(self):
        yield TreeBrowser(
            adapter=FilesystemAdapter('~/CRAP', show_hidden=False),
            id='fs-tree',
        )

    def on_tree_browser_entry_selected(self, event):
        path = event.entry.id
        self.log_write(f'selected: {path}')
```
