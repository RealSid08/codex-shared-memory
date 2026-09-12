import concurrent.futures
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shared_memory as m


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = m.Store(self.root / "store")
        self.store.ingest(
            "mac",
            {
                "MEMORY.md": "alpha beta\nalpha\nbeta\nlast\n",
                "rollout_summaries/a.md": "Foo-Bar\n",
            },
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def call(self, name, **args):
        return m.call(self.store, name, args)

    def test_scope_list_and_pagination(self):
        first = self.call("list", path="machines/mac", max_results=1)
        self.assertTrue(first["truncated"])
        second = self.call("list", path="machines/mac", cursor=first["next_cursor"])
        self.assertEqual(
            second["entries"],
            [{"path": "machines/mac/rollout_summaries", "entry_type": "directory"}],
        )
        self.assertEqual(
            self.call("list", path="machines/mac/MEMORY.md")["entries"][0][
                "entry_type"
            ],
            "file",
        )
        for path in (
            "../auth.json",
            "/etc/passwd",
            "machines/../mac",
            "machines\\mac",
            "a//b",
            ".git",
        ):
            with self.assertRaises(ValueError):
                self.call("list", path=path)
        with self.assertRaises(ValueError):
            self.call("list", cursor="9000")

    def test_read_lines(self):
        r = self.call("read", path="machines/mac/MEMORY.md", line_offset=2, max_lines=2)
        self.assertEqual(r["content"], "alpha\nbeta\n")
        self.assertTrue(r["truncated"])
        self.assertEqual(
            self.call("read", path="machines/mac/MEMORY.md", line_offset=5)["content"],
            "",
        )
        with self.assertRaises(ValueError):
            self.call("read", path="machines/mac/MEMORY.md", line_offset=6)

    def test_search_modes(self):
        scope = {"path": "machines/mac/MEMORY.md", "queries": ["alpha", "beta"]}
        self.assertEqual(len(self.call("search", **scope)["matches"]), 3)
        same = self.call("search", **scope, match_mode={"type": "all_on_same_line"})
        self.assertEqual([x["match_line_number"] for x in same["matches"]], [1])
        window = self.call(
            "search", **scope, match_mode={"type": "all_within_lines", "line_count": 2}
        )
        self.assertEqual([x["match_line_number"] for x in window["matches"]], [1, 2])
        self.assertEqual(window["matches"][1]["content"], "alpha\nbeta")
        norm = self.call(
            "search", queries=["foo_bar"], normalized=True, case_sensitive=False
        )
        self.assertEqual(
            norm["matches"][0]["path"], "machines/mac/rollout_summaries/a.md"
        )
        context = self.call(
            "search", queries=["last"], context_lines=1, path="machines/mac/MEMORY.md"
        )
        self.assertEqual(context["matches"][0]["content_start_line_number"], 3)

    def test_validation(self):
        bad = [
            ("list", {"oops": 2}),
            ("list", {"max_results": True}),
            ("search", {"queries": []}),
            ("search", {"queries": [" "]}),
            ("search", {"queries": ["-"], "normalized": True}),
            (
                "search",
                {
                    "queries": ["a"],
                    "match_mode": {"type": "all_within_lines", "line_count": 0},
                },
            ),
            ("read", {"path": "MEMORY.md", "max_lines": 0}),
        ]
        for name, args in bad:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                m.call(self.store, name, args)

    def test_atomic_snapshot_and_isolation(self):
        self.store.ingest("server-node", {"MEMORY.md": "Server independent"})
        with self.assertRaises(ValueError):
            self.store.ingest(
                "mac", {"MEMORY.md": "replacement", "auth.json": "should fail"}
            )
        self.assertIn(
            "alpha", self.call("read", path="machines/mac/MEMORY.md")["content"]
        )
        self.store.ingest("mac", {"memory_summary.md": "new"})
        self.assertNotIn("machines/mac/MEMORY.md", self.store.all_files())
        self.assertIn("machines/server-node/MEMORY.md", self.store.all_files())
        with patch.object(m, "MAX_STORE", 1), self.assertRaises(ValueError):
            self.store.ingest("server-node", {"MEMORY.md": "quota rejected"})
        self.assertEqual(
            self.store.all_files()["machines/server-node/MEMORY.md"],
            "Server independent",
        )

    def test_concurrent_append_only(self):
        name = "2026-09-08T00-00-00-concurrency-test.md"

        def write(_):
            store = m.Store(self.root / "store")
            try:
                return m.call(
                    store,
                    "add_ad_hoc_note",
                    {"filename": name, "note": "shared reference"},
                )
            except ValueError:
                return "duplicate"
            finally:
                store.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(4)))
        self.assertEqual(results.count({}), 1)
        self.assertEqual(results.count("duplicate"), 3)
        self.assertEqual(
            self.call("read", path=f"extensions/ad_hoc/notes/{name}")["content"],
            "shared reference",
        )

    def test_secret_hygiene_and_symlinks(self):
        self.store.ingest(
            "server-node",
            {"MEMORY.md": "password: not-a-real-password\nnormal fact"},
        )
        self.assertNotIn(
            "not-a-real-password",
            self.store.all_files()["machines/server-node/MEMORY.md"],
        )
        with self.assertRaises(ValueError):
            self.call(
                "add_ad_hoc_note",
                filename="2026-09-08T00-00-00-secret-test.md",
                note="api_key: dummy",
            )
        native = self.root / "native"
        native.mkdir()
        (native / "MEMORY.md").symlink_to(self.root / "elsewhere")
        self.assertEqual(m.snapshot(native), {})
        with self.assertRaises(ValueError):
            m.snapshot(self.root / "missing")

    def test_sync_and_offline_cache(self):
        native = self.root / "native"
        native.mkdir()
        (native / "MEMORY.md").write_text("Windows testing fact")
        (native / "raw_memories.md").write_text("never share this")
        cfg = {
            "machine": "windows",
            "native_memory": str(native),
            "cache": str(self.root / "cache"),
            "exchange_command": [
                sys.executable,
                m.__file__,
                "exchange",
                "--data",
                str(self.root / "store"),
            ],
        }
        config = self.root / "config.json"
        config.write_text(json.dumps(cfg))
        m.sync(config)
        self.assertIn(
            "Windows testing fact", self.store.all_files()["machines/windows/MEMORY.md"]
        )
        self.assertFalse(
            (self.root / "cache/machines/windows/raw_memories.md").exists()
        )
        cached = (self.root / "cache/machines/mac/MEMORY.md").read_text()
        cfg["exchange_command"] = [sys.executable, "-c", "raise SystemExit(1)"]
        config.write_text(json.dumps(cfg))
        with self.assertRaises(RuntimeError):
            m.sync(config)
        self.assertEqual(
            (self.root / "cache/machines/mac/MEMORY.md").read_text(), cached
        )

    def test_backup_restore(self):
        result = self.store.backup()
        import sqlite3

        with closing(sqlite3.connect(result["backup"])) as restored:
            self.assertEqual(
                restored.execute("SELECT count(*) FROM files").fetchone()[0], 2
            )
            self.assertEqual(
                restored.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )

    def test_portable_store_defaults_and_mount_guard(self):
        self.assertNotIn("/srv/", m.DEFAULT_DATA)
        with self.assertRaisesRegex(ValueError, "Required mount is unavailable"):
            m.Store(self.root / "guarded", require_mount=self.root / "not-mounted")

    def test_mcp_transport(self):
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"queries": ["alpha"]}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "read", "arguments": {"path": "../auth.json"}},
            },
        ]
        proc = subprocess.run(
            [sys.executable, m.__file__, "serve", "--data", str(self.root / "store")],
            input="\n".join(json.dumps(r) for r in requests) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(replies), 4)
        self.assertEqual(
            [t["name"] for t in replies[1]["result"]["tools"]],
            ["list", "read", "search", "add_ad_hoc_note"],
        )
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertTrue(replies[3]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
