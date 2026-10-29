import json
import plistlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_client
import install_server
from sharedmem import harnesses, install, scheduler


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_remote_command_is_portable_and_quoted(self):
        args = install_client.parse_args(
            [
                "--machine",
                "test-node",
                "--ssh-host",
                "memory-server",
                "--remote-data",
                "~/memory data",
                "--skip-mcp",
            ]
        )
        with patch.object(install.shutil, "which", return_value="/usr/bin/ssh"):
            exchange, serve = install.build_commands(
                args, "/usr/bin/python3", self.root / "shared_memory.py"
            )
        self.assertEqual(exchange[-2], "memory-server")
        self.assertIn('"$HOME"/', exchange[-1])
        self.assertIn("exchange", exchange[-1])
        self.assertIn("serve", serve[-1])
        combined = " ".join(exchange + serve)
        self.assertNotIn("/home/", combined)
        self.assertNotIn("/Users/", combined)

    def test_local_client_install_end_to_end(self):
        codex_home = self.root / "codex"
        (codex_home / "memories").mkdir(parents=True)
        (codex_home / "memories/MEMORY.md").write_text("synthetic portable fact\n")
        team = self.root / "team-notes"
        team.mkdir()
        (team / "plan.md").write_text("team fact\n")
        install_dir = self.root / "client"
        args = install_client.parse_args(
            [
                "--machine",
                "test-node",
                "--local-data",
                str(self.root / "server-data"),
                "--codex-home",
                str(codex_home),
                "--install-dir",
                str(install_dir),
                "--source",
                "codex",
                "--markdown",
                f"team={team}",
                "--min-free-bytes",
                "0",
                "--skip-mcp",
                "--skip-instructions",
                "--skip-scheduler",
            ]
        )
        with redirect_stdout(StringIO()):
            result = install.install_client(args)
        config = json.loads((install_dir / "client.json").read_text())
        self.assertEqual(config["version"], 2)
        self.assertEqual(sorted(config["sources"]), ["codex", "team"])
        self.assertFalse(result["mcp_registered"])
        self.assertEqual(
            result["mcp_command"][-3:],
            ["serve", "--config", str(install_dir / "client.json")],
        )
        self.assertTrue((install_dir / "sharedmem/cli.py").is_file())
        cache = codex_home / "shared-memories/machines/test-node"
        self.assertEqual(
            (cache / "codex/MEMORY.md").read_text(), "synthetic portable fact\n"
        )
        self.assertEqual((cache / "team/plan.md").read_text(), "team fact\n")

    def test_server_install_without_scheduler(self):
        install_dir, data = self.root / "server", self.root / "data"
        args = install_server.parse_args(
            [
                "--install-dir",
                str(install_dir),
                "--data-dir",
                str(data),
                "--min-free-bytes",
                "0",
                "--skip-backup-scheduler",
            ]
        )
        with redirect_stdout(StringIO()):
            result = install.install_server(args)
        self.assertTrue((data / "memory.sqlite3").is_file())
        self.assertIsNone(result["backup_scheduler"])
        self.assertEqual(
            json.loads((install_dir / "server.json").read_text())["data"], str(data)
        )

    def test_instruction_block_is_replaced_not_duplicated(self):
        path = self.root / "AGENTS.md"
        path.write_text("# Existing\n")
        self.assertEqual(
            harnesses.update_instructions(path, self.root / "cache"), "updated"
        )
        self.assertEqual(
            harnesses.update_instructions(path, self.root / "cache"), "unchanged"
        )
        content = path.read_text()
        self.assertEqual(content.count(harnesses.START_MARKER), 1)
        self.assertIn("Lookup is discretionary", content)
        self.assertTrue(path.with_name("AGENTS.md.before-shared-memory").exists())

    def test_instruction_update_refuses_malformed_markers_and_respects_policy(self):
        path = self.root / "AGENTS.md"
        path.write_text(harnesses.START_MARKER)
        with self.assertRaisesRegex(SystemExit, "malformed"):
            harnesses.update_instructions(path, self.root / "cache")
        own = self.root / "own.md"
        own.write_text("## Shared memory\nMy own rules.\n")
        self.assertIn(
            "skipped", harnesses.update_instructions(own, self.root / "cache")
        )
        self.assertEqual(own.read_text(), "## Shared memory\nMy own rules.\n")

    def test_symlinked_instructions_are_written_once(self):
        shared = self.root / "AGENTS.md"
        shared.write_text("# Policy\n")
        home = self.root / "home"
        for link in (home / ".codex/AGENTS.md", home / ".claude/CLAUDE.md"):
            link.parent.mkdir(parents=True)
            link.symlink_to(shared)
        selected = [
            harnesses.Codex(home, "/bin/codex"),
            harnesses.ClaudeCode(home, "/bin/claude"),
        ]
        report = harnesses.apply(selected, ["py", "serve"], "/cache", register=False)
        self.assertEqual(report["codex"]["instructions"], "updated")
        self.assertIn(
            "shared with another harness", report["claude-code"]["instructions"]
        )
        self.assertEqual(shared.read_text().count(harnesses.START_MARKER), 1)

    def test_harness_registrations(self):
        home = self.root / "home"
        with (
            patch.object(harnesses, "run") as run,
            patch.object(harnesses.subprocess, "run"),
        ):
            harnesses.Codex(home, "/opt/codex", home / "alt-codex").register(
                ["py", "serve"]
            )
            command, env = run.call_args.args[0], run.call_args.kwargs["env"]
            self.assertEqual(
                command[:4], ["/opt/codex", "mcp", "add", "shared_memories"]
            )
            self.assertEqual(env["CODEX_HOME"], str(home / "alt-codex"))
            harnesses.ClaudeCode(home, "/opt/claude").register(["py", "serve"])
            self.assertEqual(
                run.call_args.args[0][:6],
                ["/opt/claude", "mcp", "add", "--scope", "user", "shared_memories"],
            )
        opencode = home / ".config/opencode/opencode.json"
        opencode.parent.mkdir(parents=True)
        opencode.write_text(
            json.dumps({"mcp": {"other": {"type": "local"}}, "theme": "x"})
        )
        harnesses.OpenCode(home).register(["py", "serve"])
        data = json.loads(opencode.read_text())
        self.assertEqual(data["mcp"]["shared_memories"]["command"], ["py", "serve"])
        self.assertIn("other", data["mcp"])
        self.assertEqual(data["theme"], "x")
        harnesses.Cursor(home).register(["py", "serve", "--config", "c.json"])
        cursor = json.loads((home / ".cursor/mcp.json").read_text())
        self.assertEqual(
            cursor["mcpServers"]["shared_memories"],
            {"command": "py", "args": ["serve", "--config", "c.json"]},
        )
        opencode.write_text("{ // jsonc\n}")
        with self.assertRaisesRegex(SystemExit, "not plain JSON"):
            harnesses.OpenCode(home).register(["py"])

    def test_tool_output_stays_off_installer_stdout(self):
        for module in (harnesses, scheduler):
            with patch.object(module.subprocess, "run") as mocked:
                module.run(["tool", "--flag"])
            self.assertIs(mocked.call_args.kwargs["stdout"], sys.stderr)

    def test_interpreter_path_is_not_resolved(self):
        real = self.root / "cpython-3.11.16/bin/python3.11"
        real.parent.mkdir(parents=True)
        real.touch()
        stable = self.root / "cpython-3.11"
        stable.symlink_to(self.root / "cpython-3.11.16")
        with patch.object(install.sys, "executable", str(stable / "bin/python3.11")):
            self.assertEqual(install.interpreter(), str(stable / "bin/python3.11"))

    def test_scheduler_definitions(self):
        command = ["python3", "shared_memory.py", "sync"]
        with (
            patch.object(scheduler.platform, "system", return_value="Darwin"),
            patch.object(scheduler.os, "getuid", return_value=501, create=True),
            patch.object(scheduler, "run"),
            patch.object(scheduler.subprocess, "run"),
        ):
            plist = Path(scheduler.schedule("sync", command, self.root, 120))
        definition = plistlib.loads(plist.read_bytes())
        self.assertEqual(definition["Label"], "codex-shared-memory.sync")
        self.assertEqual(definition["ProgramArguments"], command)
        for kind, interval, expected in (
            ("sync", 120, "OnUnitActiveSec=120s"),
            ("backup", 86400, "Persistent=true"),
        ):
            with (
                patch.object(scheduler.platform, "system", return_value="Linux"),
                patch.object(scheduler, "run") as mocked,
            ):
                timer = Path(scheduler.schedule(kind, command, self.root, interval))
            self.assertIn(expected, timer.read_text())
            self.assertEqual(mocked.call_count, 2)
        with (
            patch.object(scheduler.platform, "system", return_value="Windows"),
            patch.object(scheduler, "run") as mocked,
        ):
            self.assertEqual(
                scheduler.schedule("sync", command, self.root, 120),
                "CodexSharedMemorySync",
            )
        self.assertIn("schtasks", mocked.call_args.args[0][0])


if __name__ == "__main__":
    unittest.main()
