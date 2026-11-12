<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/chrome.py 77bd4fb883bb5ca74ed4cb5989c8bb2491690f85 -->
gppu.chrome starts a Selenium Chrome driver on a Chrome profile that a previous run may have left locked or in a crashed state. It also switches that driver between iPhone emulation and desktop mode.

## How the pieces fit

The module has no classes. `prepare_driver` is the entry point, and `switch_to_mobile` and `switch_to_desktop` act on the driver it returns. The underscore-prefixed helpers are internal.

Before it starts Chrome, `prepare_driver` makes the profile usable. It finds running Chrome processes whose command line names the profile. Unless `interactive` is False, it asks before closing them, and it exits the program if the answer is anything other than `y` or `yes`. It sends the processes a TERM signal and waits 5 seconds. Any process still running gets KILL, and the program exits if any survive. It then removes the `SingletonLock`, `SingletonCookie`, and `SingletonSocket` files, marks the profile's last exit as normal and clean in its `Preferences` file, and deletes `DevToolsActivePort`.

Next, `prepare_driver` builds the Chrome options. Downloads go to `download_directory` without a prompt, and PDFs download instead of opening in Chrome. The system Chrome at `/opt/google/chrome/chrome` is used when that file exists. Chrome starts with `--disable-gpu`, `--no-sandbox`, and `--disable-dev-shm-usage`. The function returns a `webdriver.Chrome`.

`switch_to_mobile` sets a 375 by 812 viewport at device scale 3 and an iPhone user agent, using Chrome DevTools Protocol commands. Its `device` argument is accepted, but the body never reads it, so every call emulates the same iPhone. `switch_to_desktop` clears the viewport override and restores the user agent by taking the browser's own user agent and removing the words `Mobile` and `iPhone`.

The process handling calls `pgrep` and `kill`, so the module expects a POSIX host.

## Usage

```python
from gppu.chrome import prepare_driver, switch_to_mobile, switch_to_desktop

driver = prepare_driver()
driver.get("https://example.com")
switch_to_mobile(driver)
switch_to_desktop(driver)
```

With no arguments, `prepare_driver` uses the profile `~/.config/chrome-automation` and asks before it closes a running Chrome on that profile. Pass `interactive=False` to close it without asking.
