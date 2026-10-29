#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Launcher for the shared agent memory service. The implementation lives in sharedmem/.

Kept at this path so existing MCP registrations, SSH exchange commands and schedules
(`python3 shared_memory.py serve|exchange|sync|backup|status`) keep working.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sharedmem.cli import entry

if __name__ == "__main__":
    entry()
