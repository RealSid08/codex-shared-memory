#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install a sync client, register detected agent harnesses, and schedule sync."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sharedmem.install import client_parser, install_client


def parse_args(argv=None):
    return client_parser().parse_args(argv)


def main(argv=None):
    install_client(parse_args(argv))


if __name__ == "__main__":
    main()
