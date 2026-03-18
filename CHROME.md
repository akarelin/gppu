# gppu.chrome - Chrome Automation

Selenium Chrome driver setup with profile management, process lifecycle handling, crash recovery, and device emulation.

```python
from gppu.chrome import prepare_driver, switch_to_mobile, switch_to_desktop
```

Requires `selenium>=4.0.0`: `pip install "gppu[chrome] @ git+ssh://git@github.com/akarelin/gppu.git@gppu/latest"`

## prepare_driver

Creates a ready-to-use Selenium Chrome driver with a persistent profile.

```python
driver = prepare_driver(
    download_directory='~/Downloads',
    user_data_dir='~/.config/chrome-automation',  # default
    profile_directory='Default',                   # optional subfolder
    interactive=True,                              # prompt before killing Chrome
)
```

**What it does (in order):**

1. Expands `user_data_dir` path (`~` → home)
2. Kills any running Chrome instances using the same profile
   - `interactive=True`: prompts before killing
   - `interactive=False`: kills silently
   - Sends SIGTERM first, waits up to 5s, then SIGKILL if needed
3. Removes stale lock files (`SingletonLock`, `SingletonCookie`, `SingletonSocket`)
4. Clears crash recovery flags in `Preferences` (`exit_type` → `"Normal"`, `exited_cleanly` → `true`)
5. Removes stale `DevToolsActivePort` file
6. Configures Chrome options:
   - Sets download directory (no prompt)
   - Opens PDFs externally
   - Uses system Chrome at `/opt/google/chrome/chrome` if present
   - Flags: `--disable-gpu`, `--no-sandbox`, `--disable-dev-shm-usage`
7. Returns `webdriver.Chrome` instance

## Device Emulation

CDP-based mobile/desktop switching on a live driver session.

```python
# Switch to iPhone X emulation (375x812, 3x scale, portrait)
switch_to_mobile(driver)
switch_to_mobile(driver, device='iPhone X')  # device param reserved for future use

# Switch back to desktop (clears device metrics, restores user agent)
switch_to_desktop(driver)
```

## Process Management (internal)

These functions are used internally by `prepare_driver` but are also importable:

```python
from gppu.chrome import _pgrep, _chrome_pids, _remove_stale_locks, _clear_crash_state, _ensure_profile_unlocked

_pgrep('chrome')                    # list of "PID command" lines
_chrome_pids('/path/to/profile')    # list of PIDs using that profile
_remove_stale_locks('/path/to/profile')  # removes Singleton* files
_clear_crash_state('/path/to/profile')   # fixes Preferences JSON
_ensure_profile_unlocked('/path/to/profile', timeout=5.0, interactive=True)
```

## Defaults

```python
DEFAULT_PROFILE = "~/.config/chrome-automation"
SYSTEM_CHROME = "/opt/google/chrome/chrome"
```
