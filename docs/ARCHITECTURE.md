# Architecture

## Components

1. A native-memory snapshot on each client. Only the allowlisted Markdown files are read.
2. A client sync process that sends one complete machine snapshot to the server and receives the complete shared view.
3. A SQLite store on the server. Each machine owns one namespace, while explicit notes use a separate owner.
4. A local Markdown cache on each client. MCP reads go directly to the server; file tools can use the cache when the server is unavailable.
5. A stdio MCP server started locally or through SSH by the consuming client.

There is no long-running network listener. With SSH transport, the MCP client launches the server process through an authenticated SSH session.

## Data flow

```text
native memories -> allowlist/redaction -> exchange over stdio/SSH -> SQLite
       ^                                                        |
       |                                                        v
local cache <- atomic per-file refresh <- complete shared snapshot

MCP client -> stdio/SSH -> list, read, search, add_ad_hoc_note -> SQLite
```

Snapshot replacement is transactional per source machine. A successful empty-but-valid snapshot removes that machine's prior published files. A missing or symlinked native-memory directory is rejected so a broken path cannot erase a machine snapshot.

## Stored paths

- `machines/<machine-id>/MEMORY.md`
- `machines/<machine-id>/memory_summary.md`
- `machines/<machine-id>/rollout_summaries/*.md`
- `extensions/ad_hoc/notes/<timestamp>-<slug>.md`

The root `MEMORY.md`, root `memory_summary.md`, and `extensions/ad_hoc/instructions.md` are generated views. They are not ingested from clients.

## Consistency

- Server ingestion and note creation use SQLite write transactions.
- Sync uses an OS-released SQLite lock so two scheduled client syncs do not overlap.
- Cache files are replaced atomically one at a time. A reader can briefly see a mix of old and new files during refresh.
- Offline writes are not queued. A failed note write is reported to the MCP client.
- Daily backups use SQLite's backup API, integrity-check the copy, and keep three dated files.

## Limits

- 512 KiB per file
- 32 MiB per machine snapshot
- 128 MiB total stored text
- 2,000 files per machine
- 192 MiB maximum exchange payload
- 60,000 characters returned by one `read` call
- 200 search matches and 2,000 list entries per page

These limits are intended for concise Markdown memory, not attachments or conversation archives.
