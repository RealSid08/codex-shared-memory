#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check that the repository contains no obvious private deployment artifacts."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
CONTENT_RULES = {
    "absolute user home path": re.compile(r"/(?:Users|home)/[^/<\s`\"']+"),
    "IPv4 address": re.compile(
        r"(?<![A-Za-z0-9])(?:\d{1,3}\.){3}\d{1,3}(?![A-Za-z0-9])"
    ),
    "private tailnet hostname": re.compile(r"\b[a-z0-9.-]+\.ts\.net\b", re.IGNORECASE),
    "private key block": re.compile(r"-----BEGIN [^-\n]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}\b"),
    "OpenAI-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}
FORBIDDEN_TRACKED_NAMES = {
    "client.json",
    "server.json",
    "memory.sqlite3",
    "memory.sqlite3-shm",
    "memory.sqlite3-wal",
    "raw_memories.md",
}
REQUIRED = {
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "README.md",
    "RELEASE-CHECKLIST.md",
    "SECURITY.md",
    "docs/PROVENANCE.md",
    "install_client.py",
    "install_server.py",
    "shared_memory.py",
}


def repository_files():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def check(public_release=False):
    failures = []
    relative = {path.relative_to(ROOT).as_posix() for path in repository_files()}
    missing = REQUIRED - relative
    if missing:
        failures.append("missing required files: " + ", ".join(sorted(missing)))
    for path_text in sorted(relative):
        path = ROOT / path_text
        if path.name in FORBIDDEN_TRACKED_NAMES or path.suffix in {".sqlite3", ".log"}:
            failures.append(f"runtime/private artifact is not ignored: {path_text}")
        if path.resolve() == SELF or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"unexpected binary file: {path_text}")
            continue
        for label, pattern in CONTENT_RULES.items():
            match = pattern.search(content)
            if match:
                line = content.count("\n", 0, match.start()) + 1
                failures.append(f"{label} in {path_text}:{line}")
    if public_release:
        if not any((ROOT / name).exists() for name in ("LICENSE", "LICENSE.md")):
            failures.append("public release requires a LICENSE file")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        if "does not yet have a public vulnerability-reporting channel" in security:
            failures.append(
                "public release requires a private security-reporting channel"
            )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        if "> Release candidate:" in readme:
            failures.append(
                "public name and release-candidate status are still pending"
            )
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-release", action="store_true")
    args = parser.parse_args(argv)
    failures = check(args.public_release)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("release check passed")
    if not args.public_release:
        print(
            "public-release gates were not requested; license and security contact remain pending"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
