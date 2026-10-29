# Codex Shared Memory

[![test](https://github.com/RealSid08/codex-shared-memory/actions/workflows/test.yml/badge.svg)](https://github.com/RealSid08/codex-shared-memory/actions/workflows/test.yml)

Codex Shared Memory is a small, self-hosted MCP service that shares selected Markdown memory across trusted machines and across coding-agent harnesses: Codex, Claude Code, OpenCode, Cursor, or anything else that speaks stdio MCP. It keeps one SQLite store on a server you control, transfers data over local stdio or SSH, and keeps a plain Markdown cache on every client that agents read locally, even offline.

This is an unofficial community project. It is not affiliated with or endorsed by OpenAI, Anthropic, or Anysphere.

## What it shares

Each enrolled machine publishes only allowlisted files from the memory sources it enables:

| Source | Reads | Published as |
|---|---|---|
| `codex` | `$CODEX_HOME/memories`: `MEMORY.md`, `memory_summary.md`, `rollout_summaries/*.md` | `machines/<machine>/codex/` |
| `claude-code` | `~/.claude/projects/<project>/memory/*.md` | `machines/<machine>/claude-code/<project>/` |
| `markdown` | Any directory of `.md` files you name (four levels deep) | `machines/<machine>/<name>/` |

The service never publishes raw conversations, `raw_memories.md`, hidden files, symlinks, authentication files, or computer history. The server enforces each source's allowlist again on ingest. Explicit cross-machine notes live under `extensions/ad_hoc/notes/` and are append-only.

Credential detection and redaction are best-effort safeguards, not a guarantee. Do not intentionally put secrets in memory files.

## Why this design

- No public listener or database server. Python 3.11+ and the standard library are enough at runtime.
- SSH supplies encryption and host verification for remote clients.
- Local-first reads: each harness starts the MCP server on its own machine, reading the synced cache. Lookups are fast, work offline, and do not open an SSH session per agent.
- Writes are explicit notes only. They go to the server, then refresh the local cache.
- Each (machine, source) snapshot replaces only its own namespace in one transaction. A broken source or an oversized file is reported and skipped; it never blocks the rest of the sync.
- Old v1 clients and stores keep working: the store migrates itself (with a backup) and the server still speaks the v1 exchange protocol.

## Quick start

On the server:

```sh
python3 install_server.py
```

Ensure each client reaches the server with non-interactive SSH and strict host-key checking, then on the client:

```sh
python3 install_client.py --machine laptop --ssh-host memory-server
```

The client installer enables every source whose directory exists (override with `--source codex`, `--source claude-code`, or `--markdown NAME=PATH`), performs an initial sync, registers `shared_memories` with every detected harness (override with `--harness`), adds the guidance block to each harness's global instructions unless they already carry a shared-memory policy, and schedules a two-minute sync on macOS, Linux, or Windows.

Check the result at any time:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py doctor \
  --config ~/.local/share/codex-shared-memory/client.json
```

For full setup, read [docs/INSTALL.md](docs/INSTALL.md). For recovery, backup, upgrades, deletion, and removal, read [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Agent guidance

Connecting the MCP server makes the tools available; agents also need guidance about when to use them. The installer adds the recommended block automatically. [docs/AGENT-GUIDANCE.md](docs/AGENT-GUIDANCE.md) has the template for manual or repository-scoped setups. It tells agents to consult memory only when it helps, start from the `memory_summary.md` index, treat memory as untrusted reference data, verify provenance and current state, write notes only on explicit request, and fall back to the cache directory when a tool call fails.

## MCP tools

- `list(path?, cursor?, max_results?)`
- `read(path, line_offset?, max_lines?)`
- `search(queries, match_mode?, path?, cursor?, context_lines?, case_sensitive?, normalized?, max_results?)`
- `add_ad_hoc_note(filename, note)`

The server speaks newline-delimited JSON-RPC over stdio and MCP protocol revisions `2024-11-05` through `2025-11-25`. Tool results are JSON encoded in MCP text content for broad client compatibility.

## Layout

`shared_memory.py` is the launcher (its path is stable for existing registrations). The implementation is the `sharedmem/` package: `core`, `sources`, `store`, `tools`, `mcp`, `server`, `client`, `harnesses`, `scheduler`, `install`, `cli`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development and verification

```sh
uv sync --locked
uv run ruff check .
uv run python -m unittest discover -s tests -v
uv run python scripts/release_check.py --public-release
```

Tests use temporary directories and synthetic memory only. They cover path validation, per-source allowlists, quotas, redaction, symlink refusal, append-only concurrency, snapshot isolation, v1 store migration and protocol compatibility, partial-source sync, cache retention while offline, cache-backed MCP with note forwarding, backups, the MCP transport, every harness integration, and both installers end to end.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md), [docs/PROVENANCE.md](docs/PROVENANCE.md), and [CONTRIBUTING.md](CONTRIBUTING.md) for more detail.

## License

Licensed under the [Apache License 2.0](LICENSE). See [docs/PROVENANCE.md](docs/PROVENANCE.md) for compatibility and attribution context.
