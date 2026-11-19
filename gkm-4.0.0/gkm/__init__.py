# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Bobby Comet
"""Griffin Kernel Manager."""
__version__ = "4.0.0"
APP_VERSION = __version__

# Bumped whenever the GUI starts relying on helper behaviour that older
# installed copies of /usr/lib/gkm/gkm-helper do not have. The 3.0.x helper
# has no "version" subcommand and is treated as protocol 1.
HELPER_PROTOCOL = 4
