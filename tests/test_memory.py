import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sharedmem import client, core, server, sources
from sharedmem.store import Store
from sharedmem.tools import call

LAUNCHER = str(ROOT / "shared_memory.py")
CODEX = "machines/mac/codex"


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "store", min_free_bytes=0)
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
        return call(self.store, name, args)

    def exchange_command(self):
        return [
            sys.executable,
            LAUNCHER,
            "exchange",
            "--data",
            str(self.root / "store"),
            "--min-free-bytes",
            "0",
        ]

    def test_scope_list_and_pagination(self):
        first = self.call("list", path=CODEX, max_results=1)
        self.assertTrue(first["truncated"])
        second = self.call("list", path=CODEX, cursor=first["next_cursor"])
        self.assertEqual(
            second["entries"],
            [{"path": f"{CODEX}/rollout_summaries", "entry_type": "directory"}],
        )
        self.assertEqual(
            self.call("list", path=f"{CODEX}/MEMORY.md")["entries"][0]["entry_type"],
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
        r = self.call("read", path=f"{CODEX}/MEMORY.md", line_offset=2, max_lines=2)
        self.assertEqual(r["content"], "alpha\nbeta\n")
        self.assertTrue(r["truncated"])
        self.assertEqual(
            self.call("read", path=f"{CODEX}/MEMORY.md", line_offset=5)["content"], ""
        )
        with self.assertRaises(ValueError):
            self.call("read", path=f"{CODEX}/MEMORY.md", line_offset=6)

    def test_search_modes(self):
        scope = {"path": f"{CODEX}/MEMORY.md", "queries": ["alpha", "beta"]}
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
        self.assertEqual(norm["matches"][0]["path"], f"{CODEX}/rollout_summaries/a.md")
        context = self.call(
            "search", queries=["last"], context_lines=1, path=f"{CODEX}/MEMORY.md"
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
                call(self.store, name, args)

    def test_atomic_snapshot_and_isolation(self):
        self.store.ingest("server-node", {"MEMORY.md": "Server independent"})
        with self.assertRaises(ValueError):
            self.store.ingest(
                "mac", {"MEMORY.md": "replacement", "auth.json": "should fail"}
            )
        self.assertIn("alpha", self.call("read", path=f"{CODEX}/MEMORY.md")["content"])
        self.store.ingest("mac", {"memory_summary.md": "new"})
        self.assertNotIn(f"{CODEX}/MEMORY.md", self.store.all_files())
        self.assertIn("machines/server-node/codex/MEMORY.md", self.store.all_files())
        with patch.object(core, "MAX_STORE", 1), self.assertRaises(ValueError):
            self.store.ingest("server-node", {"MEMORY.md": "quota rejected"})
        self.assertEqual(
            self.store.all_files()["machines/server-node/codex/MEMORY.md"],
            "Server independent",
        )

    def test_sources_are_isolated_and_allowlisted(self):
        self.store.ingest_many(
            "mac",
            {
                "claude-code": (
                    "claude-code",
                    {"app/MEMORY.md": "- [x](x.md)", "app/x.md": "claude fact"},
                ),
                "notes": ("markdown", {"team/plan.md": "markdown fact"}),
            },
        )
        files = self.store.all_files()
        self.assertEqual(files["machines/mac/claude-code/app/x.md"], "claude fact")
        self.assertIn(f"{CODEX}/MEMORY.md", files)  # other sources untouched
        self.assertIn(
            "machines/mac/claude-code/app/MEMORY.md", files["memory_summary.md"]
        )
        for source, kind, path in (
            ("claude-code", "claude-code", "deep/er/x.md"),
            ("codex", "codex", "raw_memories.md"),
            ("notes", "markdown", "raw_memories.md"),
            ("Bad", "markdown", "a.md"),
            ("x", "unknown", "a.md"),
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.store.ingest_many("mac", {source: (kind, {path: "nope"})})
        with patch.object(core, "MAX_HOST", 10), self.assertRaises(ValueError):
            self.store.ingest_many("mac", {"notes": ("markdown", {"a.md": "x" * 20})})
        self.assertEqual(files["machines/mac/notes/team/plan.md"], "markdown fact")

    def test_concurrent_append_only(self):
        name = "2026-09-08T00-00-00-concurrency-test.md"

        def write(_):
            store = Store(self.root / "store", min_free_bytes=0)
            try:
                return call(
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
            "server-node", {"MEMORY.md": "password: not-a-real-password\nok"}
        )
        self.assertNotIn(
            "not-a-real-password",
            self.store.all_files()["machines/server-node/codex/MEMORY.md"],
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
        files, skipped = sources.collect("codex", native)
        self.assertEqual(files, {})
        self.assertEqual(skipped[0]["reason"], "symlink")
        with self.assertRaises(ValueError):
            sources.collect("codex", self.root / "missing")

    def test_source_collection(self):
        codex = self.root / "codex"
        (codex / "rollout_summaries").mkdir(parents=True)
        (codex / "MEMORY.md").write_text("fact")
        (codex / "raw_memories.md").write_text("never share")
        (codex / "rollout_summaries/r.md").write_text("summary")
        (codex / "memory_summary.md").write_text("x" * (core.MAX_FILE + 1))
        files, skipped = sources.collect("codex", codex)
        self.assertEqual(sorted(files), ["MEMORY.md", "rollout_summaries/r.md"])
        self.assertEqual(skipped[0]["path"], "memory_summary.md")
        claude = self.root / "projects"
        for slug in ("-Users-me-work-app", "-Users-me--t3-scratch", "-Users-me"):
            (claude / slug / "memory").mkdir(parents=True)
            (claude / slug / "memory/MEMORY.md").write_text(slug)
        (claude / "-Users-me-empty").mkdir()
        with patch.object(sources.Path, "home", return_value=Path("/", "Users", "me")):
            files, _ = sources.collect("claude-code", claude)
        self.assertEqual(
            sorted(files),
            ["home/MEMORY.md", "t3-scratch/MEMORY.md", "work-app/MEMORY.md"],
        )
        self.assertTrue(all(sources.allowed("claude-code", p) for p in files))

    def test_v1_store_migrates_with_backup(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        with closing(sqlite3.connect(legacy / "memory.sqlite3")) as db:
            db.executescript(
                "CREATE TABLE files(path TEXT PRIMARY KEY, content TEXT NOT NULL, owner TEXT NOT NULL);"
                "CREATE TABLE machines(id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, digest TEXT NOT NULL);"
                "INSERT INTO files VALUES('machines/pi/MEMORY.md','pi fact','pi');"
                "INSERT INTO files VALUES('extensions/ad_hoc/notes/n.md','note','@notes');"
                "INSERT INTO machines VALUES('pi','2026-01-01T00:00:00+00:00','d');"
            )
            db.commit()
        store = Store(legacy, min_free_bytes=0)
        try:
            files = store.all_files()
            self.assertEqual(files["machines/pi/codex/MEMORY.md"], "pi fact")
            self.assertEqual(files["extensions/ad_hoc/notes/n.md"], "note")
            self.assertEqual(store.status()["sources"][0]["source"], "codex")
            self.assertTrue((legacy / "backups/pre-v2-migration.sqlite3").is_file())
        finally:
            store.close()
        Store(legacy, min_free_bytes=0).close()  # reopening is a no-op

    def test_v1_and_v2_exchange_protocols(self):
        legacy = server.handle(
            self.store, {"machine": "old", "files": {"MEMORY.md": "v1"}}
        )
        self.assertEqual(legacy["ingest"]["files"], 1)
        self.assertEqual(legacy["files"]["machines/old/codex/MEMORY.md"], "v1")
        empty = server.handle(
            self.store, {"protocol": 2, "op": "sync", "machine": "new", "sources": {}}
        )
        self.assertEqual(empty["ingest"]["sources"], {})
        note = server.handle(
            self.store,
            {
                "protocol": 2,
                "op": "note",
                "filename": "2026-09-08T00-00-00-protocol-note.md",
                "note": "hello",
            },
        )
        self.assertEqual(note["note"], "created")
        with self.assertRaises(ValueError):
            server.handle(self.store, {"protocol": 3})
        # v1 clients reject response files over 512 KiB, so they never receive them
        big = "x" * (server.V1_MAX_FILE + 1)
        self.store.ingest("big", {"MEMORY.md": big})
        view = server.handle(self.store, {"machine": "old", "files": {}})["files"]
        self.assertNotIn("machines/big/codex/MEMORY.md", view)
        self.assertIn("machines/big/codex/MEMORY.md", self.store.all_files())

    def test_sync_offline_cache_and_partial_sources(self):
        native = self.root / "native"
        native.mkdir()
        (native / "MEMORY.md").write_text("Windows testing fact")
        (native / "raw_memories.md").write_text("never share this")
        cfg = {
            "machine": "windows",
            "native_memory": str(native),  # v1 config shape still works
            "cache": str(self.root / "cache"),
            "exchange_command": self.exchange_command(),
        }
        config = self.root / "config.json"
        config.write_text(json.dumps(cfg))
        client.sync(config)
        self.assertIn(
            "Windows testing fact",
            self.store.all_files()["machines/windows/codex/MEMORY.md"],
        )
        self.assertFalse(
            (self.root / "cache/machines/windows/codex/raw_memories.md").exists()
        )
        cached = (self.root / f"cache/{CODEX}/MEMORY.md").read_text()
        cfg["sources"] = {
            "codex": {"type": "codex", "path": str(native)},
            "claude-code": {"type": "claude-code", "path": str(self.root / "no")},
        }
        config.write_text(json.dumps(cfg))
        status = client.sync(config)
        self.assertIn("claude-code", status["source_errors"])
        self.assertIn("codex", status["sources"])
        cfg["exchange_command"] = [sys.executable, "-c", "raise SystemExit(1)"]
        config.write_text(json.dumps(cfg))
        with self.assertRaises(RuntimeError):
            client.sync(config)
        self.assertEqual((self.root / f"cache/{CODEX}/MEMORY.md").read_text(), cached)
        self.assertTrue((self.root / "cache/error.json").exists())

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "needs POSIX permissions")
    def test_unreadable_directories_fail_the_source_not_the_sync(self):
        native, notes = self.root / "native", self.root / "notes"
        (native / "rollout_summaries").mkdir(parents=True)
        (native / "MEMORY.md").write_text("still synced")
        (notes / "sub").mkdir(parents=True)
        (notes / "sub/a.md").write_text("published once")
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "machine": "laptop",
                    "cache": str(self.root / "cache"),
                    "exchange_command": self.exchange_command(),
                    "sources": {
                        "codex": {"type": "codex", "path": str(native)},
                        "notes": {"type": "markdown", "path": str(notes)},
                    },
                }
            )
        )
        client.sync(config)
        (notes / "sub").chmod(0)
        try:
            with self.assertRaises(ValueError):
                sources.collect("markdown", notes)
            status = client.sync(config)
        finally:
            (notes / "sub").chmod(0o700)
        self.assertIn("notes", status["source_errors"])
        files = self.store.all_files()
        self.assertEqual(files["machines/laptop/notes/sub/a.md"], "published once")
        self.assertEqual(files["machines/laptop/codex/MEMORY.md"], "still synced")

    def test_disabled_sources_are_pruned(self):
        native, notes = self.root / "native", self.root / "notes"
        native.mkdir()
        notes.mkdir()
        (notes / "a.md").write_text("temporary")
        cfg = {
            "machine": "laptop",
            "cache": str(self.root / "cache"),
            "exchange_command": self.exchange_command(),
            "sources": {
                "codex": {"type": "codex", "path": str(native)},
                "notes": {"type": "markdown", "path": str(notes)},
            },
        }
        config = self.root / "config.json"
        config.write_text(json.dumps(cfg))
        client.sync(config)
        self.assertIn("machines/laptop/notes/a.md", self.store.all_files())
        del cfg["sources"]["notes"]
        config.write_text(json.dumps(cfg))
        self.assertEqual(client.sync(config)["removed_sources"], ["notes"])
        self.assertNotIn("machines/laptop/notes/a.md", self.store.all_files())
        self.assertIn(
            f"{CODEX}/MEMORY.md", self.store.all_files()
        )  # other machines kept

    def test_migration_backup_is_never_overwritten(self):
        first = self.store._snapshot("pre-v2-migration.sqlite3", keep_existing=True)
        original = first.read_bytes()
        self.store.ingest("later", {"MEMORY.md": "after the backup"})
        again = self.store._snapshot("pre-v2-migration.sqlite3", keep_existing=True)
        self.assertEqual(again.read_bytes(), original)
        self.assertEqual(list(first.parent.glob(".backup-*")), [])

    def test_cache_backend_reads_locally_and_forwards_notes(self):
        native = self.root / "native"
        native.mkdir()
        (native / "MEMORY.md").write_text("local first")
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "machine": "laptop",
                    "cache": str(self.root / "cache"),
                    "exchange_command": self.exchange_command(),
                    "sources": {"codex": {"type": "codex", "path": str(native)}},
                }
            )
        )
        backend = client.CacheBackend(config)
        with self.assertRaises(RuntimeError):
            backend.files()  # never synced
        client.sync(config)
        found = call(backend, "search", {"queries": ["local first"]})
        self.assertEqual(found["matches"][0]["path"], "machines/laptop/codex/MEMORY.md")
        name = "2026-09-08T00-00-00-forwarded-note.md"
        self.assertEqual(
            call(backend, "add_ad_hoc_note", {"filename": name, "note": "via cache"}),
            {},
        )
        self.assertEqual(
            call(backend, "read", {"path": f"extensions/ad_hoc/notes/{name}"})[
                "content"
            ],
            "via cache",
        )

    def test_backup_restore(self):
        result = self.store.backup()
        with closing(sqlite3.connect(result["backup"])) as restored:
            self.assertEqual(
                restored.execute("SELECT count(*) FROM files").fetchone()[0], 2
            )
            self.assertEqual(
                restored.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )

    def test_portable_store_defaults_and_mount_guard(self):
        self.assertNotIn("/srv/", core.DEFAULT_DATA)
        with self.assertRaisesRegex(ValueError, "Required mount is unavailable"):
            Store(self.root / "guarded", require_mount=self.root / "not-mounted")

    def mcp(self, *arguments, extra=()):
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
            *extra,
        ]
        proc = subprocess.run(
            [sys.executable, LAUNCHER, "serve", *arguments],
            input="\n".join(json.dumps(r) for r in requests) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        return [json.loads(line) for line in proc.stdout.splitlines()]

    def test_mcp_transport_store_and_cache_modes(self):
        replies = self.mcp("--data", str(self.root / "store"))
        self.assertEqual(len(replies), 4)
        self.assertEqual(
            [t["name"] for t in replies[1]["result"]["tools"]],
            ["list", "read", "search", "add_ad_hoc_note"],
        )
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertTrue(replies[3]["result"]["isError"])
        native = self.root / "native"
        native.mkdir()
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "machine": "laptop",
                    "cache": str(self.root / "cache"),
                    "exchange_command": self.exchange_command(),
                    "sources": {"codex": {"type": "codex", "path": str(native)}},
                }
            )
        )
        client.sync(config)
        note = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "add_ad_hoc_note",
                "arguments": {
                    "filename": "2026-09-08T00-00-00-mcp-note.md",
                    "note": "over mcp",
                },
            },
        }
        replies = self.mcp("--config", str(config), extra=[note])
        self.assertEqual(len(replies), 5)  # stdout stays pure JSON-RPC after a sync
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertFalse(replies[4]["result"]["isError"])
        self.assertIn(
            "extensions/ad_hoc/notes/2026-09-08T00-00-00-mcp-note.md",
            self.store.all_files(),
        )


if __name__ == "__main__":
    unittest.main()
