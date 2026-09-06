#!/usr/bin/env python3
"""Launch the shared gppufs browser."""

import runpy
from pathlib import Path


if __name__ == '__main__':
  runpy.run_path(str(Path(__file__).with_name('handler_browser.py')), run_name='__main__')
