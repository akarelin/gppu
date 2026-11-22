"""
gppu.chrome — Selenium Chrome automation utilities.

Provides a shared Chrome driver setup with automation profile management,
process lifecycle handling, and mobile/desktop emulation.

Usage:
    from gppu.chrome import prepare_driver, switch_to_mobile, switch_to_desktop

    driver = prepare_driver()
    driver.get("https://example.com")
"""

import json
import subprocess
import sys
import time

from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from .gppu import Path


# .. -- Defaults (overridable via prepare_driver kwargs) --
DEFAULT_PROFILE = "~/.config/chrome-automation"
SYSTEM_CHROME = Path("/opt/google/chrome/chrome")


# region - Chrome Process Management
# .. ##########################################################################
# .. Chrome Process Management
# .. ##########################################################################
# endregion

def _pgrep(pattern: str) -> List[str]:
  try:
    out = subprocess.check_output(["pgrep", "-af", pattern], text=True)
    return out.splitlines()
  except subprocess.CalledProcessError as e:
    if e.returncode == 1: return []   # .. pgrep matched no process
    raise


def _chrome_pids(profile: str) -> List[int]:
  lines = _pgrep("chrome")
  return [int(l.split(maxsplit=1)[0]) for l in lines if profile in l]


def _remove_stale_locks(user_data_dir: Path) -> None:
  """Remove stale SingletonLock / SingletonCookie left after a Chrome crash."""
  for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
    lock = user_data_dir / name
    if lock.exists() or lock.is_symlink():
      lock.unlink()


def _clear_crash_state(user_data_dir: Path, profile_directory: Optional[str] = None) -> None:
  """Clear Chrome crash recovery flags so it starts cleanly under Selenium."""
  prefs_path = user_data_dir / (profile_directory or "Default") / "Preferences"
  if not prefs_path.exists(): return

  with prefs_path.open() as f:
    prefs = json.load(f)
  changed = False
  if prefs.get("profile", {}).get("exit_type") != "Normal":
    prefs.setdefault("profile", {})["exit_type"] = "Normal"
    changed = True
  if not prefs.get("profile", {}).get("exited_cleanly"):
    prefs.setdefault("profile", {})["exited_cleanly"] = True
    changed = True
  if changed:
    with prefs_path.open("w") as f:
      json.dump(prefs, f)


def _ensure_profile_unlocked(profile: Path, timeout: float = 5.0, interactive: bool = True) -> None:
  pids = _chrome_pids(str(profile))

  if pids:
    if interactive:
      ans = input(f"Chrome is running with {profile}. Close it so the script can automate? [y/N]: ").strip().lower()
      if ans not in {"y", "yes"}: sys.exit("Aborted – close Chrome and rerun.")
    else:
      print(f"Closing Chrome ({len(pids)} processes using {profile})...")

    subprocess.run(["kill", "-TERM", *map(str, pids)], check=False)

    end = time.time() + timeout
    while time.time() < end and _chrome_pids(str(profile)): time.sleep(0.25)

    if _chrome_pids(str(profile)):
      subprocess.run(["kill", "-KILL", *map(str, _chrome_pids(str(profile)))], check=False)
      time.sleep(1)

    if _chrome_pids(str(profile)): sys.exit("Could not close Chrome – aborting.")

  _remove_stale_locks(profile)


# region - Driver Preparation
# .. ##########################################################################
# .. Driver Preparation
# .. ##########################################################################
# endregion

def prepare_driver(
    download_directory: str = "~/Downloads",
    user_data_dir: str = DEFAULT_PROFILE,
    profile_directory: Optional[str] = None,
    interactive: bool = True,
) -> webdriver.Chrome:
  """Prepare a Selenium Chrome driver with a Chrome profile.

  Args:
      download_directory:  Where Chrome saves downloads.
      user_data_dir:       Path to --user-data-dir (e.g. ~/.config/google-chrome).
      profile_directory:   Profile subfolder (e.g. "Default", "Profile 1"). Optional.
      interactive:         If True, prompt before killing Chrome. If False, kill silently.
  """
  user_data_dir = Path(user_data_dir)   # .. Path expands its ~
  _ensure_profile_unlocked(user_data_dir, interactive=interactive)
  _clear_crash_state(user_data_dir, profile_directory)

  options = webdriver.ChromeOptions()
  prefs = {
      "download.default_directory": str(Path(download_directory)),   # .. Chrome is given the folder, its ~ expanded
      "download.prompt_for_download": False,
      "plugins.always_open_pdf_externally": True
  }
  options.add_experimental_option("prefs", prefs)

  if SYSTEM_CHROME.exists(): options.binary_location = str(SYSTEM_CHROME)

  options.add_argument(f"--user-data-dir={user_data_dir}")
  if profile_directory:
    options.add_argument(f"--profile-directory={profile_directory}")
  options.add_argument("--disable-gpu")
  options.add_argument("--no-sandbox")
  options.add_argument("--disable-dev-shm-usage")

  # .. Remove stale DevToolsActivePort
  devtools_port = user_data_dir / "DevToolsActivePort"
  if devtools_port.exists():
    devtools_port.unlink()

  service = Service()
  driver = webdriver.Chrome(service=service, options=options)

  return driver


# region - Mobile / Desktop Emulation
# .. ##########################################################################
# .. Mobile / Desktop Emulation
# .. ##########################################################################
# endregion

def switch_to_mobile(driver: webdriver.Chrome, device: str = "iPhone X") -> None:
  """Switch driver to mobile emulation mode."""
  driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
    "mobile": True,
    "width": 375,
    "height": 812,
    "deviceScaleFactor": 3,
    "screenOrientation": {"type": "portraitPrimary", "angle": 0}
  })
  driver.execute_cdp_cmd("Emulation.setUserAgentOverride", {
    "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
                 "Mobile/15E148 Safari/604.1"
  })


def switch_to_desktop(driver: webdriver.Chrome) -> None:
  """Switch driver to desktop mode."""
  driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})
  driver.execute_cdp_cmd("Emulation.setUserAgentOverride", {
    "userAgent": driver.execute_script("return navigator.userAgent").replace("Mobile", "").replace("iPhone", "")
  })
