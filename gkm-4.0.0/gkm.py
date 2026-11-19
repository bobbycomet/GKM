#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Launcher: lets `python3 gkm.py` (and the .deb's /usr/lib/gkm/gkm.py) run the package."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from gkm.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
