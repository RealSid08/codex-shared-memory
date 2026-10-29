#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install the shared-memory stdio server and optional backup schedule."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sharedmem.install import install_server, server_parser


def parse_args(argv=None):
    return server_parser().parse_args(argv)


def main(argv=None):
    install_server(parse_args(argv))


if __name__ == "__main__":
    main()
