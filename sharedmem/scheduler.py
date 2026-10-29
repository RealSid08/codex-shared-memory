# SPDX-License-Identifier: Apache-2.0
"""Periodic jobs: launchd (macOS), systemd user timers (Linux), Task Scheduler (Windows).

Job names are unchanged from v1 so upgrades replace existing schedules in place.
"""

import os
import platform
import plistlib
import shlex
import subprocess
import tempfile
from pathlib import Path

from .core import atomic_write

JOBS = {
    # kind: (launchd label, systemd unit stem, Windows task, run at start, start delay)
    "sync": (
        "codex-shared-memory.sync",
        "codex-shared-memory-sync",
        "CodexSharedMemorySync",
        True,
        "30s",
    ),
    "backup": (
        "codex-shared-memory.backup",
        "codex-shared-memory-backup",
        "CodexSharedMemoryBackup",
        False,
        "5min",
    ),
}


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def schedule(kind, command, home, interval_seconds):
    label, unit, task, at_start, delay = JOBS[kind]
    home = Path(home)
    system = platform.system()
    if system == "Darwin":
        plist = home / "Library/LaunchAgents" / (label + ".plist")
        plist.parent.mkdir(exist_ok=True, parents=True)
        payload = plistlib.dumps(
            {
                "Label": label,
                "ProgramArguments": command,
                "RunAtLoad": at_start,
                "StartInterval": interval_seconds,
                "ProcessType": "Background",
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
        domain = f"gui/{os.getuid()}"
        subprocess.run(
            ["launchctl", "bootout", f"{domain}/{label}"],
            capture_output=True,
            check=False,
        )
        run(["launchctl", "bootstrap", domain, str(plist)])
        return str(plist)
    if system == "Linux":
        units = home / ".config/systemd/user"
        units.mkdir(exist_ok=True, parents=True)
        quoted = " ".join(shlex.quote(value) for value in command)
        service, timer = units / f"{unit}.service", units / f"{unit}.timer"
        atomic_write(
            service,
            f"[Unit]\nDescription=Shared agent memory {kind}\n\n"
            f"[Service]\nType=oneshot\nExecStart={quoted}\nUMask=0077\n",
        )
        persistent = "Persistent=true\n" if kind == "backup" else ""
        atomic_write(
            timer,
            f"[Unit]\nDescription=Shared agent memory {kind} timer\n\n"
            f"[Timer]\nOnStartupSec={delay}\nOnUnitActiveSec={interval_seconds}s\n"
            f"{persistent}\n[Install]\nWantedBy=timers.target\n",
        )
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "enable", "--now", timer.name])
        return str(timer)
    if system == "Windows":
        python = Path(command[0])
        pythonw = python.with_name("pythonw.exe")
        scheduled = [str(pythonw) if pythonw.exists() else str(python), *command[1:]]
        minutes = max(1 if kind == "sync" else 5, (interval_seconds + 59) // 60)
        run(
            [
                "schtasks",
                "/Create",
                "/TN",
                task,
                "/SC",
                "MINUTE",
                "/MO",
                str(minutes),
                "/TR",
                subprocess.list2cmdline(scheduled),
                "/F",
            ]
        )
        return task
    raise SystemExit(
        f"Unsupported OS scheduler; skip scheduling and run the {kind} command manually"
    )
