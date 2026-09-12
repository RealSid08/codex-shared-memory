import json
import plistlib
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import install_client
import install_server


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
                "--skip-codex",
            ]
        )
        with patch.object(install_client.shutil, "which", return_value="/usr/bin/ssh"):
            exchange, serve = install_client.build_commands(
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
        native = codex_home / "memories"
        native.mkdir(parents=True)
        (native / "MEMORY.md").write_text("synthetic portable fact\n")
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
                "--min-free-bytes",
                "0",
                "--skip-codex",
                "--skip-instructions",
                "--skip-scheduler",
            ]
        )
        with redirect_stdout(StringIO()):
            result = install_client.install(args)
        config = json.loads((install_dir / "client.json").read_text())
        self.assertEqual(config["machine"], "test-node")
        self.assertFalse(result["mcp_registered"])
        published = codex_home / "shared-memories/machines/test-node/MEMORY.md"
        self.assertEqual(published.read_text(), "synthetic portable fact\n")

    def test_server_install_without_scheduler(self):
        install_dir = self.root / "server"
        data = self.root / "data"
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
            result = install_server.install(args)
        self.assertTrue((data / "memory.sqlite3").is_file())
        self.assertIsNone(result["backup_scheduler"])
        saved = json.loads((install_dir / "server.json").read_text())
        self.assertEqual(saved["data"], str(data))

    def test_instruction_block_is_replaced_not_duplicated(self):
        path = self.root / "AGENTS.md"
        path.write_text("# Existing\n")
        install_client.update_instructions(path, self.root / "codex")
        install_client.update_instructions(path, self.root / "codex")
        content = path.read_text()
        self.assertEqual(content.count(install_client.START_MARKER), 1)
        self.assertIn("Lookup is discretionary", content)
        self.assertTrue(path.with_name("AGENTS.md.before-shared-memory").exists())

    def test_instruction_update_refuses_malformed_markers(self):
        path = self.root / "AGENTS.md"
        path.write_text(install_client.START_MARKER)
        with self.assertRaisesRegex(SystemExit, "malformed"):
            install_client.update_instructions(path, self.root / "codex")

    def test_codex_registration_uses_selected_codex_home(self):
        codex_home = self.root / "alternate-codex"
        with patch.object(install_client, "run") as mocked:
            install_client.register_codex(
                "/opt/codex", codex_home, ["python3", "server.py", "serve"]
            )
        command = mocked.call_args.args[0]
        environment = mocked.call_args.kwargs["env"]
        self.assertEqual(command[:4], ["/opt/codex", "mcp", "add", "shared_memories"])
        self.assertEqual(environment["CODEX_HOME"], str(codex_home))

    def test_client_scheduler_definitions(self):
        command = ["python3", "shared_memory.py", "sync"]
        with (
            patch.object(install_client.platform, "system", return_value="Darwin"),
            patch.object(install_client.os, "getuid", return_value=501, create=True),
            patch.object(install_client, "run"),
            patch.object(install_client.subprocess, "run"),
        ):
            result = install_client.schedule_sync(command, self.root, 120)
        plist = Path(result)
        definition = plistlib.loads(plist.read_bytes())
        self.assertEqual(definition["Label"], "codex-shared-memory.sync")
        self.assertEqual(definition["ProgramArguments"], command)

        with (
            patch.object(install_client.platform, "system", return_value="Linux"),
            patch.object(install_client, "run") as mocked,
        ):
            result = install_client.schedule_sync(command, self.root, 120)
        self.assertTrue(Path(result).is_file())
        self.assertIn("OnUnitActiveSec=120s", Path(result).read_text())
        self.assertEqual(mocked.call_count, 2)

        with (
            patch.object(install_client.platform, "system", return_value="Windows"),
            patch.object(install_client, "run") as mocked,
        ):
            result = install_client.schedule_sync(command, self.root, 120)
        self.assertEqual(result, "CodexSharedMemorySync")
        self.assertIn("schtasks", mocked.call_args.args[0][0])

    def test_server_linux_backup_definition(self):
        command = ["python3", "shared_memory.py", "backup"]
        with (
            patch.object(install_server.platform, "system", return_value="Linux"),
            patch.object(install_server, "run") as mocked,
        ):
            result = install_server.schedule_backup(command, self.root, 86400)
        self.assertTrue(Path(result).is_file())
        self.assertIn("OnUnitActiveSec=86400s", Path(result).read_text())
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
