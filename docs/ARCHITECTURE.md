# Architecture

## Components

1. **Sources** (`sharedmem/sources.py`). Each enabled source reads one harness's native memory through a strict allowlist: `codex`, `claude-code`, or a generic `markdown` directory. Adding a harness means adding one allowlist and one collector.
2. **Client sync** (`sharedmem/client.py`). Collects every enabled source, sends one snapshot per source to the server, and receives the complete shared view.
3. **Store** (`sharedmem/store.py`). One SQLite database on the server. Each (machine, source) pair owns one namespace; explicit notes use a separate owner. Root index files are generated views.
4. **Local cache**. A plain Markdown tree on each client, refreshed atomically per file. Agents can read it with file tools when everything else fails.
5. **MCP server** (`sharedmem/mcp.py`, `sharedmem/tools.py`). A stdio JSON-RPC server with `list`, `read`, `search`, and `add_ad_hoc_note`. It runs over either backend:
   - cache-backed (`serve --config client.json`, the default for clients): reads the local cache; note writes go to the server, then refresh the cache;
   - store-backed (`serve --data ...`, used on the server or over SSH by v1 setups).
6. **Exchange handler** (`sharedmem/server.py`). Run by the client through `exchange_command` (local process or SSH). Handles v1 sync, v2 sync, v2 note, and status requests.
7. **Harness integrations** (`sharedmem/harnesses.py`). Register `shared_memories` and the guidance block with Codex, Claude Code, OpenCode, and Cursor.

There is no long-running network listener. Over SSH, each exchange runs as an authenticated SSH command.

## Data flow

```text
codex / claude-code / markdown sources
        -> allowlist + redaction -> exchange (stdio/SSH) -> SQLite store
                                                               |
local Markdown cache <- atomic per-file refresh <- complete shared view

harness MCP client -> local serve --config -> list/read/search from cache
                                           -> add_ad_hoc_note -> exchange -> SQLite -> sync
```

## Exchange protocol

- v1: `{"machine", "files"}`. Stored as the machine's `codex` source. The response omits files over 512 KiB, which v1 clients would reject.
- v2 sync: `{"protocol": 2, "op": "sync", "machine", "sources": {name: {"type", "files"}}}`. Each named source is replaced atomically and all of them in one transaction. An empty `sources` still returns the shared view.
- v2 note: `{"protocol": 2, "op": "note", "filename", "note"}`.
- status: `{"op": "status"}`. Read-only store summary for `doctor`.

## Stored paths

- `machines/<machine>/codex/MEMORY.md`, `memory_summary.md`, `rollout_summaries/*.md`
- `machines/<machine>/claude-code/<project>/<name>.md`
- `machines/<machine>/<markdown-source>/<path>.md`
- `extensions/ad_hoc/notes/<timestamp>-<slug>.md`

The root `MEMORY.md`, root `memory_summary.md`, and `extensions/ad_hoc/instructions.md` are generated, never ingested. The summary lists every machine, source, file count, and last sync, with direct paths to each source's index files.

## Schema and upgrades

The store records its schema in `PRAGMA user_version`. Opening a v1 store (paths `machines/<machine>/<file>`, a `machines` table) writes `backups/pre-v2-migration.sqlite3`, then migrates in one transaction: snapshots move under their `codex` source, and the `sources` table replaces `machines`. Upgrade the server first; v1 clients keep syncing until they are upgraded.

## Consistency

- Server ingestion and note creation use SQLite write transactions.
- Sync uses an OS-released SQLite lock so two scheduled client syncs do not overlap.
- Cache files are replaced atomically one at a time. A reader can briefly see a mix of old and new files during refresh.
- A source whose directory is missing or symlinked is reported in `status.json` and not sent, so the server keeps its previous copy instead of publishing an empty replacement.
- An oversized or unreadable file is skipped and listed in `status.json`; the rest of the source still syncs.
- Offline writes are not queued. A failed note write is reported to the MCP client.
- Daily backups use SQLite's backup API, integrity-check the copy, and keep three dated files.

## Limits

- 2 MiB per file (512 KiB for files delivered to v1 clients)
- 32 MiB per machine across all sources
- 128 MiB total stored text
- 4,000 files per source snapshot
- 192 MiB maximum exchange payload
- 60,000 characters returned by one `read` call
- 200 search matches and 2,000 list entries per page

These limits are intended for concise Markdown memory, not attachments or conversation archives.
