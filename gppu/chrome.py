"""
gppu.chrome — Selenium Chrome automation utilities.

Provides a shared Chrome driver setup with automation profile management,
process lifecycle handling, and mobile/desktop emulation.

Usage:
    from gppu.chrome import prepare_driver, switch_to_mobile, switch_to_desktop

    driver = prepare_driver()
    driver.get("https://example.com")
"""

import subprocess
import sys
import time
import os

from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.chrome.service import Service


# -- Defaults (overridable via prepare_driver kwargs) --
DEFAULT_PROFILE = os.path.expanduser("~/.config/chrome-automation")
SYSTEM_CHROME = "/opt/google/chrome/chrome"


# ##########################################################################
#                         Chrome Process Management
# ##########################################################################

def _pgrep(pattern: str) -> List[str]:
  try:
    out = subprocess.check_output(["pgrep", "-af", pattern], text=True)
    return out.splitlines()
  except subprocess.CalledProcessError:
    return []


def _chrome_pids(profile: str) -> List[int]:
  lines = _pgrep("chrome")
  return [int(l.split(maxsplit=1)[0]) for l in lines if profile in l]


def _ensure_profile_unlocked(profile: str, timeout: float = 5.0, interactive: bool = True) -> None:
  pids = _chrome_pids(profile)
  if not pids: return

  if interactive:
    ans = input(f"Chrome is running with {profile}. Close it so the script can automate? [y/N]: ").strip().lower()
    if ans not in {"y", "yes"}: sys.exit("Aborted – close Chrome and rerun.")
  else:
    print(f"Closing Chrome ({len(pids)} processes using {profile})...")

  subprocess.run(["kill", "-TERM", *map(str, pids)], check=False)

  end = time.time() + timeout
  while time.time() < end and _chrome_pids(profile): time.sleep(0.25)

  if _chrome_pids(profile):
    subprocess.run(["kill", "-KILL", *map(str, _chrome_pids(profile))], check=False)
    time.sleep(1)

  if _chrome_pids(profile): sys.exit("Could not close Chrome – aborting.")


# ##########################################################################
#                           Driver Preparation
# ##########################################################################

def prepare_driver(
    download_directory: str = "~/Downloads",
    profile: str = DEFAULT_PROFILE,
    interactive: bool = True,
) -> webdriver.Chrome:
  """Prepare a Selenium Chrome driver with the automation profile.

  Args:
      download_directory: Where Chrome saves downloads.
      profile:           Path to the Chrome user-data-dir.
      interactive:       If True, prompt before killing Chrome. If False, kill silently.
  """
  _ensure_profile_unlocked(profile, interactive=interactive)

  options = webdriver.ChromeOptions()
  prefs = {
      "download.default_directory": download_directory,
      "download.prompt_for_download": False,
      "plugins.always_open_pdf_externally": True
  }
  options.add_experimental_option("prefs", prefs)

  if os.path.exists(SYSTEM_CHROME): options.binary_location = SYSTEM_CHROME

  options.add_argument(f"--user-data-dir={profile}")
  options.add_argument("--disable-gpu")
  options.add_argument("--no-sandbox")
  options.add_argument("--disable-dev-shm-usage")

  service = Service()
  driver = webdriver.Chrome(service=service, options=options)

  return driver


# ##########################################################################
#                         Mobile / Desktop Emulation
# ##########################################################################

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
