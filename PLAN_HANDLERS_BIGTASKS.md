# gppu.handlers Big tasks

Complete every unchecked item under `Big tasks` in `gppu/handlers.py` on the `handlers-bigtasks` branch.

- [x] Read OpenAI and Anthropic LLM export ZIP files as collections of sessions.
- [x] Keep harness-specific recognition and extraction out of large conditional blocks.
- [x] Move helper behavior into the classes that own it.
- [x] Support the existing handler calls from synchronous and asynchronous code through gppu async.
- [x] Derive spans for Git-tracked repositories, folders, and files from local Git history without contacting upstreams.
- [x] Verify focused behavior against generated fixtures and the named export examples.
- [x] Commit and push the completed branch.

## Formatting and in-code documentation

- [x] Format `gppu/handlers.py` with Black and four-space indentation.
- [x] Document its module, classes, methods, and public helper functions in Python docstrings.
- [x] Keep operational semantics in Python; Markdown remains supplementary.
- [x] Use gppu `full_path` rather than a private path resolver.
- [x] Add `FolderHandler`.
- [x] Add explicit `ChatGPTHandler` and `AnthropicHandler` detection for extracted folders and ZIP archives.
- [x] Compose `FileHandler` from handler mixins without constructor injection.
- [x] Add explicit Markdown and CSV handlers; preserve complete Markdown frontmatter and derive its title, name, tags, and span.
- [x] Add a log handler whose timestamped rows determine its span.
- [x] Add unimplemented image and video EXIF handler placeholders informed by CRAP photo-indexer concepts.
- [x] Read RAR metadata through the platform RARLAB command without `rarfile`.
- [x] Require Python 3.14 in package, analysis, test, and build declarations.
- [x] Make `FileHandler` a public composition base and remove library-created handler objects.
- [x] Accept copied caller metadata on handlers and expose it with probe metadata.
- [x] Keep large-tree scans running by returning per-record handler errors by default; retain explicit strict execution.
- [x] Derive CSV spans from documented timestamp columns and make additional timestamp formats a class extension.
- [x] Add native ignored-file and ignored-folder recognition from the active TextLake/FileIndexer rules, retaining ignored folder boundaries without descending into them.
- [x] Add the configured Git upstream URL to Git handler metadata without contacting the remote.
- [x] Generate `docs/handlers.md` from the Python docstrings instead of maintaining duplicate documentation.
- [x] Add `.msg` and `.eml` filename metadata handling while leaving message parsing unimplemented.
- [x] Include the complete test suite in the existing optional `run_tests` build path.
- [x] Verify behavior, commit, and push the branch.

## Large-tree follow-up

- [x] Reject unsupported Session and Archive file extensions, and empty Session files, before content inspection.
- [x] Identify Session folders from structural markers only; do not inspect their children during folder identification.
- [x] Add streaming `walk_sync` and `walk` traversal with `enter` and `on_folder_done` callbacks.
- [x] Make `identify_sync` and `probe_sync` consume the public traversal without parallel path and child dictionaries.
- [x] Derive `archive_path_sync` from one aggregate root record without materializing the hierarchy.
- [ ] Retain richer archive and folder statistics, including a breakdown by file class.
- [ ] Add focused traversal and I/O-count tests, regenerate handler documentation, run the complete suite and build, commit, and push.
