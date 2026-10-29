# SPDX-License-Identifier: Apache-2.0
"""Limits, path validation, redaction and atomic file writes shared by all modules."""

import datetime as dt
import os
import re
import tempfile
from pathlib import Path, PurePosixPath

MAX_FILE = 2 * 1024 * 1024
MAX_HOST = 32 * 1024 * 1024
MAX_STORE = 128 * 1024 * 1024
MAX_WIRE = 192 * 1024 * 1024
MAX_FILES_PER_MACHINE = 4000
DEFAULT_MIN_FREE_BYTES = 256 * 1024 * 1024
DEFAULT_DATA = "~/.local/share/codex-shared-memory/data"
NOTE_RE = r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,79}\.md"
MACHINE_RE = r"[a-z0-9][a-z0-9-]{0,63}"
SOURCE_RE = r"[a-z0-9][a-z0-9-]{0,31}"


def now():
    return dt.datetime.now(dt.UTC).isoformat()


def safe_path(path, root_ok=False):
    if not isinstance(path, str) or "\\" in path or "\x00" in path:
        raise ValueError("Invalid relative path")
    if path in ("", ".") and root_ok:
        return ""
    parts = path.split("/")
    if any(not p or p.startswith(".") or ":" in p for p in parts):
        raise ValueError("Only visible relative paths are allowed")
    return str(PurePosixPath(path))


def text_size(content):
    if not isinstance(content, str) or "\x00" in content:
        raise ValueError("Memory content must be UTF-8 text without NUL")
    size = len(content.encode("utf-8"))
    if size > MAX_FILE:
        raise ValueError(f"Memory file exceeds {MAX_FILE // 1024} KiB limit")
    return size


def redact(content):
    """Best-effort hygiene, not a guarantee of secret detection."""
    content = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|sk-[A-Za-z0-9_-]{20,})\b",
        "[REDACTED TOKEN]",
        content,
    )
    content = re.sub(
        r"(?im)^.*\b(?:password|passwd|api[_ -]?key|access[_ -]?token"
        r"|client[_ -]?secret)\s*[:=]\s*\S.*$",
        "[REDACTED CREDENTIAL LINE]",
        content,
    )
    return content


def has_symlink_part(root, relative):
    """True if any component from root down to root/relative is a symlink."""
    parts = Path(relative).parts
    return any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1))


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing symlink destination")
    fd, tmp = tempfile.mkstemp(prefix=".memory-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
