# gppu Proposed Structure — Iteration 4 (Task 1: Stabilize gppu for RAN)

Focus: **Task 1 — stabilize `gppu` for RAN** ([tui.ps1](file:///D:/Dev/RAN/Hosts/tui.ps1): mount SMB, mount S2, `tray-control`, `rewrite-commits`, and server/workstation/Pi update/preserve/maintain via `fleet-tui`, `preservator`, `configure-all`, `configs`).
Boundary: **`gppu` stays strictly general-purpose** — zero Y2-specific concepts (`Entity`, entity state/events/persistence, `Supervisor`, and `StateManager` live in `y2`, extending `gppu`'s base classes in Phase 2). Web UI and its API stay parked until the core is solid.

---

## 1. Proposed Core Structure (`gppu/gppu.py`)

Everything in `gppu` builds on the same three primitives already in [gppu.py](file:///D:/Dev/gppu/gppu/gppu.py): **`_YMRO`** (lifecycle), **`_Base`** (`mixin_Logger` + `mixin_Config`), and **`_DC`** (`UserDict` + typed properties + `_INIT_STEPS`). Zero non-`gppu` base classes.

### A. Core Primitives & Siblings (`DataObject` vs `_BaseApp` / `App`)

```python
class _YMRO:
  """Stepped lifecycle: init, load, start (and minimal stop). Runs sync or async steps cleanly."""
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']
  def _ymro(self, step: str) -> list: ...
  def _callall(self, step: str, *a, **kw) -> None: ...
  async def _acallall(self, step: str, *a, **kw) -> None: ...


class _DC(UserDict):
  """Typed dict-backed object built through extensible _INIT_STEPS (no @final on __init__)."""
  _INIT_STEPS = [_init_from_kw, _init_ymro]
  def __init__(self, **kw): ...


class DataObject(_YMRO, _Base, _DC):
  """Managed non-App object (e.g. Y2 entities/groups later). Never owns a loop; no CLI/MANIFEST.
  Reaches shared Runtime / Env / State and parent capabilities via parent / api."""
  parent: Any
  api: Any


class _BaseApp(_YMRO, _Base, _DC):
  """Shared base for Env, Runtime, and App: name, from_dict (topology/tunables/Jinja), from_file, reset."""
  name: str
  def __init(self) -> None: ...
  def from_dict(self, d: Mapping, *, override: bool = True) -> Self: ...
  def from_file(self, path: str | Path, *, override: bool = True) -> Self: ...
  def reset(self) -> None: ...


class App(_BaseApp):
  """THE one app class for all utilities, scripts, TUIs, and services (no CliApp, no separate AsyncApp).
  Loads: glob_dict(self.name) < explicit config= (or MANIFEST if no config=) < constructor **kw.
  __init never reads sys.argv (100% import-safe); cli() applies --key val / --flag overrides and runs main()."""
  def __init(self) -> None: ...
  def main(self) -> Any: ...          # override as def main(self) OR async def main(self)
  def run(self) -> Any: ...           # runs load -> start -> main() (sync directly, or via Runtime if async)

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> Any:
    """Apply --key val / --flag CLI overrides over config/manifest, then run default action."""
    ...
```

### B. The Three Shared Objects (All Built on `gppu`, Shared Differently)

```python
# 1. Environment — global read-only config + machine facts, loaded once at import
class _Env(_BaseApp):
  _ENV_PATHS = {"RAN": "RAN/_config/config.yaml", "IoT": "IoT/_Creekview/_creekview.yaml"}
  os: OSType
  host: str
  user: str
  home: Path

  def __init(self) -> None: ...       # detects machine facts, loads RAN or IoT YAML via from_file()
  def from_dict(self, d, *, override=True) -> Self: ...   # updates Logger.trace_rules

Env = _Env()
glob, glob_int, glob_list, glob_dict = ...


# 2. Runtime — one per process; owns the SINGLE asyncio loop, active apps, and parallel execution
class _Runtime(_BaseApp):
  apps: dict[str, App]                # running apps in this process by name
  _loop: asyncio.AbstractEventLoop | None
  _tasks: set[asyncio.Task]

  def attach(self, loop: asyncio.AbstractEventLoop) -> None: ...   # adopts Textual's loop in TUI
  def spawn[T](self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]: ...
  def schedule[T](self, coro: Coroutine[Any, Any, T]) -> Future[T]: ...
  async def run(self, app: App) -> Any: ...                        # runs load -> start -> main() on the one loop
  async def launch(self, cmd: list[str], line: Callable[[str], Any], cwd: str, env: dict) -> str | None: ...
  async def run_parallel(self, units, run, conflicts, failed) -> None: ...

Runtime = _Runtime()


# 3. State — pure mutable app/system state (NO events, NO listeners, NO MQTT, NO loop)
# Examples: rewrite-commits's per-repo last-update timestamps; preservator's run history; Y2 extends it in Phase 2
class _State(_YMRO, _Base, _DC):
  """Dict-backed mutable state store. Optionally loads/saves to a file (JSON/YAML) when given a path."""
  def load_state(self, path: str | Path) -> Self: ...
  def save_state(self, path: str | Path) -> None: ...

State = _State()
```

### C. TUI Layer (`gppu/tui/launcher.py`) — Zero Code for Simple Utilities

- **`TUILauncher` (config-driven):** Generates menus, mode selectors, and input prompts **on the fly from `tui.yaml` and inline `MANIFEST` blocks** — no TUI code required per utility.
- **`TUIApp(App, TextualApp)` (only for custom full-screen grids):** Always async; attaches `Runtime` to Textual's active event loop inside `_process_messages()`, captures logs to Ctrl-O panel, no `@final _DC.__init__` clash, no `AsyncApp.stop()` mismatch.
- **`gppu/app.py`:** Eliminates the duplicate `AsyncApp` loop/task/stop implementation (keeps `AsyncApp = App` as a 1-line alias only so `IoT`/`y2` imports stay intact until Phase 2).

---

## 2. How Each Active RAN Utility Works Under This Structure

| Active RAN Utility | What Changes | How It Runs |
|---|---|---|
| **[mapper.cmd](file:///D:/Dev/RAN/Hosts/mapper.cmd)** | **Stays a 5-line `.cmd` script** (unchanged; zero Python/TUI code added). | Launched directly from `tui.ps1` via its inline `MANIFEST`. |
| **[tray-control.ps1](file:///D:/Dev/RAN/Hosts/tray-control.ps1)** | **Stays a 1-line `.ps1` script** (unchanged). | Launched directly from `tui.ps1` via its inline `MANIFEST`. |
| **[synology-mount.py](file:///D:/Dev/RAN/Hosts/synology-mount.py)** | Subclasses `App` with typed fields (`server`, `action`, `pattern`); drops `argparse` and interactive `input()` menu; reads config/paths from `Env`. | **CLI:** zero-arg default or `--action unmount --pattern '*'`<br>**TUI:** `TUILauncher` generates its mode picker from `MANIFEST`<br>**Import:** `SynologyMount(action='mount', pattern='Dulled*').run()` |
| **[preservator.py](file:///D:/Dev/RAN/Hosts/preservator/preservator.py)** | Already subclasses `App` with typed `_DC` fields (`host`, `step`, `here`, `run_id`, `cells`); ends with `Preservator.cli()`. | Fixes `config=` vs `MANIFEST` bug (so tests and `Preservator(config=...)` work safely) and stops `sys.argv` leaking on import; can use `State` for run history later. |
| **[fleet-tui.py](file:///D:/Dev/RAN/Hosts/configure-all/fleet-tui.py)** | `Fleet(TUIApp)` drops its duplicated `launch()` / `run_parallel()` methods and calls `Runtime.launch()` / `Runtime.run_parallel()`. | Runs on Textual's loop with zero `@final __init__` or `stop()` warnings. |
| **[rewrite_commits.py](file:///D:/Dev/RAN/Hosts/rewrite-commits/rewrite_commits.py)** | `RewriteCommitsApp(TUIApp)` runs cleanly on fixed `TUIApp`; its per-repo last-update `state.json` is the canonical example of `State` (can adopt `_State` cleanly). | Runs via `tui.ps1` or CLI cleanly. |
| **[configure-all.py](file:///D:/Dev/RAN/Hosts/configure-all/configure-all.py)** & **[configs.py](file:///D:/Dev/RAN/Hosts/configure-all/configs.py)** | Keep working immediately via `glob`/`Info`/`jinja_template` and `tui.ps1` manifests; can drop `argparse` for `App.cli()` once core `App` is locked. | Runs via `tui.ps1` modes (`pull`/`update`/`push`), `fleet-tui`, or CLI. |
| **[fleet.py](file:///D:/Dev/RAN/Hosts/fleet.py)** & **[tui.py](file:///D:/Dev/RAN/Hosts/tui/tui.py)** | `Fleet(App)` and `App(config=ContainerApp.CONFIG)` stay clean and import-safe (no `sys.argv` bleed). | `tui.ps1` launcher menu starts and runs every active tool cleanly. |

---

## 3. Exact Task 1 Edits (Once You Approve This Structure)

1. **[gppu/gppu.py](file:///D:/Dev/gppu/gppu/gppu.py):**
   - Replace `YAsync`-on-`_BaseApp` with `_Runtime(_BaseApp)` (`Runtime`) owning the single process loop, `spawn`, `schedule`, `run`, `launch`, `run_parallel`, and `apps`.
   - Add `_State(_YMRO, _Base, _DC)` (`State`) as pure mutable dict-backed state (with `load_state`/`save_state`, zero events/MQTT).
   - Add `DataObject(_YMRO, _Base, _DC)` as sibling to `_BaseApp`.
   - Drop `@final` on `_DC.__init__`; fix `App` config order (`Env` section < `MANIFEST` if no `config=` < explicit `config=` < `**kw`) and move `sys.argv` override parsing to `App.cli()`.
2. **[gppu/app.py](file:///D:/Dev/gppu/gppu/app.py):**
   - Remove the duplicated loop/task/stop code in `AsyncApp` (keep `AsyncApp = App` as a thin compatibility alias until Phase 2).
3. **[gppu/tui/launcher.py](file:///D:/Dev/gppu/gppu/tui/launcher.py):**
   - Base `TUIApp` on `App` + `TextualApp`, attach `Runtime` to Textual's loop, fix exit cleanup.
4. **Verify & align active RAN tools:**
   - Run `gppu` tests + verify `tui.py`, `preservator.py` (including `test_preservator.py`), `fleet-tui.py`, `rewrite_commits.py`, `configure-all.py`, `configs.py`, `mapper.cmd`, `tray-control.ps1`, and convert [synology-mount.py](file:///D:/Dev/RAN/Hosts/synology-mount.py) to `App` as the clean exemplar.
