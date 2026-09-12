#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install the shared-memory stdio server and optional backup schedule."""

import argparse
import json
import os
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from shared_memory import DEFAULT_DATA, DEFAULT_MIN_FREE_BYTES, atomic_write


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def schedule_backup(command, home, interval_seconds):
    system = platform.system()
    if system == "Linux":
        units = home / ".config/systemd/user"
        units.mkdir(exist_ok=True, parents=True)
        quoted = " ".join(shlex.quote(value) for value in command)
        service = units / "codex-shared-memory-backup.service"
        timer = units / "codex-shared-memory-backup.timer"
        atomic_write(
            service,
            "[Unit]\nDescription=Back up shared Codex memory\n\n"
            f"[Service]\nType=oneshot\nExecStart={quoted}\nUMask=0077\n",
        )
        atomic_write(
            timer,
            "[Unit]\nDescription=Back up shared Codex memory periodically\n\n"
            "[Timer]\nOnStartupSec=5min\n"
            f"OnUnitActiveSec={interval_seconds}s\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n",
        )
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "enable", "--now", timer.name])
        return str(timer)
    if system == "Darwin":
        label = "codex-shared-memory.backup"
        plist = home / "Library/LaunchAgents" / (label + ".plist")
        plist.parent.mkdir(exist_ok=True, parents=True)
        payload = plistlib.dumps(
            {
                "Label": label,
                "ProgramArguments": command,
                "RunAtLoad": False,
                "StartInterval": interval_seconds,
                "StandardOutPath": "/dev/null",
                "StandardErrorPath": "/dev/null",
            }
        )
        fd, temporary = tempfile.mkstemp(prefix=".shared-memory-", dir=plist.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, plist)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            check=False,
        )
        run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])
        return str(plist)
    if system == "Windows":
        python = Path(command[0])
        pythonw = python.with_name("pythonw.exe")
        scheduled = [str(pythonw) if pythonw.exists() else str(python), *command[1:]]
        minutes = max(5, (interval_seconds + 59) // 60)
        run(
            [
                "schtasks",
                "/Create",
                "/TN",
                "CodexSharedMemoryBackup",
                "/SC",
                "MINUTE",
                "/MO",
                str(minutes),
                "/TR",
                subprocess.list2cmdline(scheduled),
                "/F",
            ]
        )
        return "CodexSharedMemoryBackup"
    raise SystemExit(
        "Unsupported OS scheduler; rerun with --skip-backup-scheduler and schedule backups manually"
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", default="~/.local/share/codex-shared-memory")
    parser.add_argument("--data-dir", default=DEFAULT_DATA)
    parser.add_argument("--require-mount")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--backup-interval-seconds", type=int, default=86400)
    parser.add_argument("--skip-backup-scheduler", action="store_true")
    return parser.parse_args(argv)


def install(args):
    os.umask(0o077)
    if args.min_free_bytes < 0 or args.backup_interval_seconds < 300:
        raise SystemExit(
            "Free-space threshold must be non-negative and backup interval at least 300"
        )
    home = Path.home()
    install_dir = Path(args.install_dir).expanduser()
    if install_dir.is_symlink():
        raise SystemExit("Refusing symlink install directory")
    install_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    script = install_dir / "shared_memory.py"
    source = Path(__file__).with_name("shared_memory.py")
    if source.resolve() != script.resolve():
        shutil.copy2(source, script)
    script.chmod(0o700)
    python = str(Path(sys.executable).resolve())
    options = [
        "--data",
        str(Path(args.data_dir).expanduser()),
        "--min-free-bytes",
        str(args.min_free_bytes),
    ]
    if args.require_mount:
        options += ["--require-mount", str(Path(args.require_mount).expanduser())]
    status_command = [python, str(script), "status", *options]
    run(status_command)
    scheduler = None
    backup_command = [python, str(script), "backup", *options]
    if not args.skip_backup_scheduler:
        scheduler = schedule_backup(backup_command, home, args.backup_interval_seconds)
    result = {
        "script": str(script),
        "data": str(Path(args.data_dir).expanduser()),
        "serve_command": [python, str(script), "serve", *options],
        "exchange_command": [python, str(script), "exchange", *options],
        "backup_scheduler": scheduler,
    }
    atomic_write(install_dir / "server.json", json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


def main(argv=None):
    install(parse_args(argv))


if __name__ == "__main__":
    main()
