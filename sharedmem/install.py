# SPDX-License-Identifier: Apache-2.0
"""Client and server installers (wrapped by install_client.py and install_server.py)."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import harnesses, scheduler
from .core import (
    DEFAULT_DATA,
    DEFAULT_MIN_FREE_BYTES,
    MACHINE_RE,
    SOURCE_RE,
    atomic_write,
)
from .sources import DEFAULT_PATHS

DEFAULT_INSTALL = "~/.local/share/codex-shared-memory"
DEFAULT_REMOTE_SCRIPT = "~/.local/share/codex-shared-memory/shared_memory.py"
DEFAULT_REMOTE_DATA = DEFAULT_DATA
PACKAGE = Path(__file__).resolve().parent
LAUNCHER = PACKAGE.parent / "shared_memory.py"


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def copy_runtime(install_dir):
    """Copy the launcher and package into install_dir; return the launcher path."""
    install_dir = Path(install_dir).expanduser()
    if install_dir.is_symlink():
        raise SystemExit("Refusing symlink install directory")
    install_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = install_dir / "shared_memory.py"
    if LAUNCHER.resolve() != script.resolve():
        shutil.copy2(LAUNCHER, script)
        target = install_dir / "sharedmem"
        staging = install_dir / ".sharedmem-new"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(PACKAGE, staging, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.rmtree(target, ignore_errors=True)
        os.replace(staging, target)
    script.chmod(0o700)
    return script


def remote_arg(value):
    """Quote one remote-shell argument while allowing a leading ~/ to expand."""
    if value.startswith("~/"):
        return '"$HOME"/' + shlex.quote(value[2:])
    return shlex.quote(value)


def remote_program(*arguments):
    return " ".join(remote_arg(value) for value in arguments)


def server_options(data, require_mount, min_free_bytes):
    options = ["--data", data, "--min-free-bytes", str(min_free_bytes)]
    if require_mount:
        options += ["--require-mount", require_mount]
    return options


def build_commands(args, python, installed_script):
    """Return (exchange_command, remote_serve_command)."""
    if args.local_data:
        prefix = [python, str(installed_script)]
        options = server_options(
            args.local_data, args.require_mount, args.min_free_bytes
        )
        return prefix + ["exchange", *options], prefix + ["serve", *options]
    ssh = shutil.which("ssh")
    if not ssh:
        raise SystemExit("Install an OpenSSH client or use --local-data")
    ssh_prefix = [
        ssh,
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={args.connect_timeout}",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "StrictHostKeyChecking=yes",
        "--",
        args.ssh_host,
    ]
    options = server_options(
        args.remote_data, args.remote_require_mount, args.min_free_bytes
    )
    exchange = remote_program(
        args.remote_python, args.remote_script, "exchange", *options
    )
    serve = remote_program(args.remote_python, args.remote_script, "serve", *options)
    return ssh_prefix + [exchange], ssh_prefix + [serve]


def resolve_sources(args, home):
    """Build the sources map from --source/--markdown, defaulting to detected ones."""
    defaults = {
        "codex": Path(args.native_memory or Path(args.codex_home) / "memories"),
        "claude-code": home / ".claude/projects",
    }
    defaults = {name: Path(str(p)).expanduser() for name, p in defaults.items()}
    requested = args.source or [name for name, p in defaults.items() if p.is_dir()]
    sources = {}
    for item in requested:
        name, _, path = item.partition("=")
        if name not in DEFAULT_PATHS:
            raise SystemExit(f"Unknown source {name}; use --markdown NAME=PATH")
        root = Path(path).expanduser() if path else defaults[name]
        sources[name] = {"type": name, "path": str(root)}
    for item in args.markdown or []:
        name, _, path = item.partition("=")
        if not re.fullmatch(SOURCE_RE, name) or not path or name in DEFAULT_PATHS:
            raise SystemExit("--markdown expects NAME=PATH with a new lowercase NAME")
        sources[name] = {"type": "markdown", "path": str(Path(path).expanduser())}
    if not sources:
        raise SystemExit("No memory sources found; pass --source or --markdown")
    for name, spec in sources.items():
        root = Path(spec["path"])
        if not root.is_dir() or root.is_symlink():
            raise SystemExit(f"Source {name} directory is missing or symlinked: {root}")
    return sources


def client_parser():
    parser = argparse.ArgumentParser(description="Install a shared-memory client.")
    parser.add_argument("--machine", required=True, help="stable lowercase machine ID")
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--ssh-host", help="OpenSSH host or alias for the server")
    location.add_argument("--local-data", help="use an on-machine store at this path")
    parser.add_argument("--remote-python", default="python3")
    parser.add_argument("--remote-script", default=DEFAULT_REMOTE_SCRIPT)
    parser.add_argument("--remote-data", default=DEFAULT_REMOTE_DATA)
    parser.add_argument("--remote-require-mount")
    parser.add_argument("--require-mount", help="required mount for --local-data")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument(
        "--source",
        action="append",
        help="enable a native source: codex or claude-code, optionally NAME=PATH "
        "(default: every source whose directory exists)",
    )
    parser.add_argument(
        "--markdown", action="append", help="publish a Markdown directory as NAME=PATH"
    )
    parser.add_argument(
        "--harness",
        action="append",
        choices=["codex", "claude-code", "opencode", "cursor"],
        help="register MCP and guidance with this harness (default: all detected)",
    )
    parser.add_argument(
        "--mcp-mode",
        choices=["local", "remote"],
        default="local",
        help="local: serve reads from the cache (default); remote: serve over SSH",
    )
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--claude", default=shutil.which("claude"))
    parser.add_argument(
        "--skip-mcp", "--skip-codex", dest="skip_mcp", action="store_true"
    )
    parser.add_argument("--skip-instructions", action="store_true")
    parser.add_argument("--skip-scheduler", action="store_true")
    parser.add_argument(
        "--codex-home", default=os.environ.get("CODEX_HOME", "~/.codex")
    )
    parser.add_argument("--native-memory", help="codex memory directory (v1 option)")
    parser.add_argument("--cache")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL)
    parser.add_argument("--interval-seconds", type=int, default=120)
    return parser


def install_client(args):
    os.umask(0o077)
    if not re.fullmatch(MACHINE_RE, args.machine):
        raise SystemExit("Invalid machine ID")
    if args.min_free_bytes < 0 or args.interval_seconds < 60:
        raise SystemExit(
            "Free-space threshold must be non-negative and interval at least 60"
        )
    if args.connect_timeout < 1:
        raise SystemExit("Connect timeout must be positive")
    home = Path.home()
    sources = resolve_sources(args, home)
    codex_home = Path(args.codex_home).expanduser()
    script = copy_runtime(args.install_dir)
    install_dir = script.parent
    python = str(Path(sys.executable).resolve())
    exchange_command, remote_serve = build_commands(args, python, script)
    config = install_dir / "client.json"
    cache = (
        Path(args.cache).expanduser() if args.cache else codex_home / "shared-memories"
    )
    atomic_write(
        config,
        json.dumps(
            {
                "version": 2,
                "machine": args.machine,
                "cache": str(cache),
                "exchange_command": exchange_command,
                "sources": sources,
            },
            indent=2,
        ),
    )
    sync_command = [python, str(script), "sync", "--config", str(config)]
    run(sync_command, stdout=subprocess.DEVNULL)
    mcp_command = (
        [python, str(script), "serve", "--config", str(config)]
        if args.mcp_mode == "local"
        else remote_serve
    )
    available = harnesses.all_harnesses(home, args.codex, codex_home, args.claude)
    selected = [
        h
        for h in available
        if (h.name in args.harness if args.harness else h.detected())
    ]
    report = harnesses.apply(
        selected,
        mcp_command,
        cache,
        register=not args.skip_mcp,
        instructions=not args.skip_instructions,
    )
    schedule = None
    if not args.skip_scheduler:
        schedule = scheduler.schedule("sync", sync_command, home, args.interval_seconds)
    result = {
        "machine": args.machine,
        "config": str(config),
        "cache": str(cache),
        "sources": sorted(sources),
        "mcp_command": mcp_command,
        "mcp_registered": not args.skip_mcp and bool(selected),
        "harnesses": report,
        "scheduler": schedule,
    }
    print(json.dumps(result, indent=2))
    return result


def server_parser():
    parser = argparse.ArgumentParser(description="Install the shared-memory server.")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL)
    parser.add_argument("--data-dir", default=DEFAULT_DATA)
    parser.add_argument("--require-mount")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--backup-interval-seconds", type=int, default=86400)
    parser.add_argument("--skip-backup-scheduler", action="store_true")
    return parser


def install_server(args):
    os.umask(0o077)
    if args.min_free_bytes < 0 or args.backup_interval_seconds < 300:
        raise SystemExit(
            "Free-space threshold must be non-negative and backup interval at least 300"
        )
    script = copy_runtime(args.install_dir)
    python = str(Path(sys.executable).resolve())
    data = str(Path(args.data_dir).expanduser())
    options = ["--data", data, "--min-free-bytes", str(args.min_free_bytes)]
    if args.require_mount:
        options += ["--require-mount", str(Path(args.require_mount).expanduser())]
    run([python, str(script), "status", *options], stdout=subprocess.DEVNULL)
    backup_command = [python, str(script), "backup", *options]
    schedule = None
    if not args.skip_backup_scheduler:
        schedule = scheduler.schedule(
            "backup", backup_command, Path.home(), args.backup_interval_seconds
        )
    result = {
        "script": str(script),
        "data": data,
        "serve_command": [python, str(script), "serve", *options],
        "exchange_command": [python, str(script), "exchange", *options],
        "backup_scheduler": schedule,
    }
    atomic_write(script.parent / "server.json", json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result
