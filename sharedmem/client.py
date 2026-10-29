# SPDX-License-Identifier: Apache-2.0
"""Client side: collect enabled sources, exchange with the server, refresh the cache.

The local cache is a plain Markdown tree, so agents can read it with file tools when
offline. `serve --config` exposes the same cache over MCP: reads never leave the
machine (fast, offline-capable, no SSH session per agent), while note writes are sent
to the server and followed by an immediate cache refresh.

client.json (v2):
  {"machine", "cache", "exchange_command": [...],
   "sources": {"codex": {"type": "codex", "path": "~/.codex/memories"}, ...}}
A v1 config ({"native_memory": ...}) is read as a single codex source.
"""

import contextlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

from .core import MAX_WIRE, atomic_write, has_symlink_part, now, safe_path, text_size
from .sources import collect

EXCHANGE_TIMEOUT = 60


def load_config(path):
    cfg = json.loads(Path(path).expanduser().read_text())
    if "sources" not in cfg:
        cfg["sources"] = {"codex": {"type": "codex", "path": cfg["native_memory"]}}
    for name, spec in cfg["sources"].items():
        spec.setdefault("type", name)
    return cfg


def exchange(cfg, request, timeout=EXCHANGE_TIMEOUT):
    proc = subprocess.run(
        cfg["exchange_command"],
        input=json.dumps(request),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(
            "Server exchange failed; existing cache retained. " + proc.stderr[-400:]
        )
    if len(proc.stdout) > MAX_WIRE:
        raise ValueError("Exchange response too large")
    return json.loads(proc.stdout)


def _cache_root(cfg):
    cache = Path(cfg["cache"]).expanduser()
    if cache.is_symlink():
        raise ValueError("Refusing symlink cache root")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    return cache.resolve()


def _write_cache(cache, files):
    if not isinstance(files, dict) or len(files) > 20000:
        raise ValueError("Invalid snapshot response")
    for path, content in files.items():
        safe_path(path)
        text_size(content)
        if has_symlink_part(cache, path):
            raise ValueError("Cache contains symlink parent")
    manifest = cache / ".manifest.json"
    old = json.loads(manifest.read_text()) if manifest.exists() else []
    for path, content in files.items():
        target = cache / path
        if not target.exists() or target.read_bytes() != content.encode():
            atomic_write(target, content)
    for path in set(old) - set(files):
        safe_path(path)
        target = cache / path
        if target.is_file() and not target.is_symlink():
            target.unlink()
    atomic_write(manifest, json.dumps(sorted(files)))


def sync(config_path):
    cfg = load_config(config_path)
    cache = _cache_root(cfg)
    # OS-released process lock works on macOS/Linux/Windows, including after crashes.
    lock = sqlite3.connect(cache / ".sync-lock.sqlite3", timeout=1)
    try:
        lock.execute("BEGIN IMMEDIATE")
        sources, skipped, errors = {}, [], {}
        for name, spec in cfg["sources"].items():
            try:
                files, missed = collect(spec["type"], spec["path"])
            except (ValueError, OSError) as error:  # keep the server's previous copy
                errors[name] = str(error)
                continue
            sources[name] = {"type": spec["type"], "files": files}
            skipped += [{"source": name, **item} for item in missed]
        response = exchange(
            cfg,
            {
                "protocol": 2,
                "op": "sync",
                "machine": cfg["machine"],
                "sources": sources,
                # sources removed from client.json are deleted on the server; ones
                # that merely failed to read above stay listed and keep their copy
                "enabled": sorted(cfg["sources"]),
            },
        )
        _write_cache(cache, response["files"])
        status = {
            "last_success": now(),
            "machine": cfg["machine"],
            "server_version": response.get("server_version", "1"),
            "sources": response["ingest"].get("sources", {}),
            "removed_sources": response.get("removed_sources", []),
            "skipped": skipped,
            "source_errors": errors,
            "cached_files": len(response["files"]),
        }
        atomic_write(cache / "status.json", json.dumps(status, indent=2))
        (cache / "error.json").unlink(missing_ok=True)
        return status  # never print here: serve() calls sync() with stdout as MCP
    except Exception as error:
        atomic_write(
            cache / "error.json",
            json.dumps({"failed_at": now(), "error": str(error)}, indent=2),
        )
        raise
    finally:
        lock.close()


class CacheBackend:
    """MCP backend that reads the local cache and forwards note writes."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.cache = _cache_root(self.cfg)
        self._key, self._files = None, {}

    def files(self):
        manifest = self.cache / ".manifest.json"
        if not manifest.exists():
            raise RuntimeError(
                "Shared memory cache is empty; run sync first (see error.json)"
            )
        key = os.stat(manifest).st_mtime_ns
        if key != self._key:
            files = {}
            for path in json.loads(manifest.read_text()):
                safe_path(path)
                target = self.cache / path
                if has_symlink_part(self.cache, path) or not target.is_file():
                    continue
                files[path] = target.read_text(encoding="utf-8")
            self._key, self._files = key, files
        return self._files

    def add_note(self, filename, note):
        response = exchange(
            self.cfg,
            {"protocol": 2, "op": "note", "filename": filename, "note": note},
            timeout=30,
        )
        if response.get("note") != "created":
            raise RuntimeError("Server did not confirm the note")
        # The note is stored; if this refresh fails the scheduled sync catches up.
        with contextlib.suppress(Exception):
            sync(self.config_path)
        return {}
