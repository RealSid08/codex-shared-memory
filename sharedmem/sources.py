# SPDX-License-Identifier: Apache-2.0
"""Readers for each harness's native memory, plus the server-side allowlists.

A source type defines which relative paths may be published (enforced again on
the server) and how a client collects them. Each client enables sources explicitly
in client.json (the installer proposes the ones it detects).

- codex: $CODEX_HOME/memories -> MEMORY.md, memory_summary.md, rollout_summaries/*.md
- claude-code: ~/.claude/projects/<project>/memory/*.md -> <project>/<name>.md
- markdown: any directory of Markdown files (up to four levels deep)

Excluded everywhere: raw conversations, raw_memories.md, hidden files, symlinks,
credentials and anything outside the allowlist.
"""

import os
import re
from pathlib import Path

from .core import MAX_FILE, has_symlink_part, redact, safe_path, text_size

CODEX_FILES = ("MEMORY.md", "memory_summary.md")


def _allowed_codex(path):
    return path in CODEX_FILES or bool(
        re.fullmatch(r"rollout_summaries/[^/]+\.md", path)
    )


def _allowed_claude(path):
    return bool(re.fullmatch(r"[^/]+/[^/]+\.md", path))


def _allowed_markdown(path):
    return bool(re.fullmatch(r"(?:[^/]+/){0,3}[^/]+\.md", path)) and not path.endswith(
        "raw_memories.md"
    )


ALLOWLISTS = {
    "codex": _allowed_codex,
    "claude-code": _allowed_claude,
    "markdown": _allowed_markdown,
}
DEFAULT_PATHS = {"codex": "~/.codex/memories", "claude-code": "~/.claude/projects"}


def allowed(source_type, path):
    check = ALLOWLISTS.get(source_type)
    if check is None:
        raise ValueError(f"Unknown source type: {source_type}")
    return check(path)


def claude_project_name(slug, home=None):
    """Turn Claude Code's path slug (-Users-me-work-app) into a readable name."""
    user = re.escape(Path(home or Path.home()).name)
    name = re.sub(rf"^-(?:Users|home)-{user}(?:-|$)", "", slug).lstrip("-")
    return name or "home"


def _read(root, relative, published, files, skipped):
    """Read one candidate file into files, or record why it was skipped."""
    if has_symlink_part(root, relative):
        skipped.append({"path": published, "reason": "symlink"})
        return
    try:
        with (root / relative).open(encoding="utf-8", newline="") as f:
            content = f.read(MAX_FILE + 1)
        text_size(content)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        skipped.append({"path": published, "reason": str(error)[:200]})
        return
    files[published] = redact(content)


def _entries(directory):
    """List a directory, turning permission and I/O errors into ValueError.

    glob/rglob silently skip unreadable directories, which would publish an empty
    or partial snapshot over the server's good copy; failing the source instead
    keeps the previous snapshot."""
    try:
        return sorted(os.scandir(directory), key=lambda e: e.name)
    except OSError as error:
        raise ValueError(f"Cannot read {directory}: {error.strerror}") from error


def _md_files(directory):
    return [e.name for e in _entries(directory) if e.name.endswith(".md")]


def collect(source_type, root):
    """Return (files, skipped) for one source. Raises if the root or any directory
    in it is unusable, so a broken path can never publish an empty replacement."""
    root = Path(root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"{source_type} memory directory missing or symlinked: {root}")
    files, skipped = {}, []
    if source_type == "codex":
        present = {e.name for e in _entries(root)}
        candidates = [Path(n) for n in CODEX_FILES if n in present]
        rollouts = root / "rollout_summaries"
        if rollouts.is_dir() and not rollouts.is_symlink():
            candidates += [Path("rollout_summaries", n) for n in _md_files(rollouts)]
        for relative in candidates:
            _read(root, relative, relative.as_posix(), files, skipped)
    elif source_type == "claude-code":
        names = {}
        for project in _entries(root):
            memory = Path(project.path) / "memory"
            if project.is_symlink() or not project.is_dir() or not memory.is_dir():
                continue
            name = claude_project_name(project.name)
            if names.setdefault(name, project.name) != project.name:
                name = project.name.lstrip("-") or "home"
            for filename in _md_files(memory):
                relative = Path(project.name, "memory", filename)
                _read(root, relative, f"{name}/{filename}", files, skipped)
    elif source_type == "markdown":
        pending = [Path()]
        while pending:
            folder = pending.pop()
            for entry in _entries(root / folder):
                relative = folder / entry.name
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir() and len(relative.parts) < 4:
                    pending.append(relative)
                elif entry.name.endswith(".md") and allowed(
                    "markdown", relative.as_posix()
                ):
                    _read(root, relative, relative.as_posix(), files, skipped)
    else:
        raise ValueError(f"Unknown source type: {source_type}")
    for path in list(files):
        try:
            safe_path(path)
        except ValueError:
            skipped.append({"path": path, "reason": "unsafe path"})
            del files[path]
    return files, skipped
