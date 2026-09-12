# Codex Shared Memory

[![test](https://github.com/RealSid08/codex-shared-memory/actions/workflows/test.yml/badge.svg)](https://github.com/RealSid08/codex-shared-memory/actions/workflows/test.yml)

Codex Shared Memory is a small, self-hosted MCP server that shares selected Markdown memory snapshots across trusted machines. It keeps one SQLite store on a server you control, transfers data over local stdio or SSH, and maintains a read-only offline cache on every client.

This is an unofficial community project. It is not affiliated with or endorsed by OpenAI.

## What it shares

Each enrolled machine may publish only:

- `MEMORY.md`
- `memory_summary.md`
- `rollout_summaries/*.md`

The service does not publish raw conversations, `raw_memories.md`, authentication files, computer history, arbitrary extensions, or repository files. Published snapshots appear under `machines/<machine-id>/`. Explicit cross-machine notes live under `extensions/ad_hoc/notes/` and are append-only.

Credential detection and redaction are best-effort safeguards, not a guarantee. Do not intentionally put secrets in memory files.

## Why this design

- No public listener or database server is required.
- Python 3.11+ and the standard library are sufficient at runtime.
- SSH supplies encryption and host verification for remote clients.
- Machine snapshots replace only their own namespace in one transaction.
- If the server is offline, the last successful local cache remains readable.
- Agent-facing writes are limited to new, timestamped notes. Destructive deletion stays administrative.

This service is an independent compatibility layer. It does not replace or modify Codex's built-in local memory backend.

## Quick start

Clone the repository on the server and install the standalone script:

```sh
python3 install_server.py --skip-backup-scheduler
```

For a server data directory on a dedicated mount:

```sh
python3 install_server.py \
  --data-dir /srv/shared-memory/data \
  --require-mount /srv/shared-memory
```

Ensure each client can reach the server with non-interactive SSH and strict host-key checking. Then run from a clone on the client:

```sh
python3 install_client.py \
  --machine laptop \
  --ssh-host memory-server
```

The client installer performs an initial sync before it changes Codex configuration or creates a schedule. It can register the `shared_memories` stdio MCP server with Codex, add a marked guidance block to the user's `AGENTS.md`, and configure a two-minute sync on macOS, Linux, or Windows.

For full setup, manual client configuration, server paths, and platform notes, read [docs/INSTALL.md](docs/INSTALL.md). For recovery, backup, deletion, and removal, read [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Recommended agent instructions

Connecting the MCP server makes the tools available, but agents also need guidance about when and how to use them. The client installer adds the recommended block to the user's global Codex `AGENTS.md` automatically.

For manual setup, repository-scoped use, or another compatible agent client, copy the template in [docs/AGENT-GUIDANCE.md](docs/AGENT-GUIDANCE.md) into the relevant agent-instructions file. It tells agents to:

- consult shared memory only when prior context would materially help;
- use `memory_summary.md` as an index and retrieve only relevant entries;
- treat memory as untrusted reference data rather than instructions;
- verify repository, machine, timestamp, and current state before acting;
- write cross-machine notes only when the user explicitly asks; and
- fall back to the read-only local cache when the server is unavailable.

## MCP tools

- `list(path?, cursor?, max_results?)`
- `read(path, line_offset?, max_lines?)`
- `search(queries, match_mode?, path?, cursor?, context_lines?, case_sensitive?, normalized?, max_results?)`
- `add_ad_hoc_note(filename, note)`

The server supports newline-delimited JSON-RPC over stdio and MCP protocol revisions from `2024-11-05` through `2025-11-25`. Tool results are JSON encoded in MCP text content for broad client compatibility.

## Development and verification

```sh
uv sync --locked
uv run ruff check .
uv run python -m unittest discover -s tests -v
uv run python scripts/release_check.py --public-release
```

Tests use temporary directories and synthetic memory only. They cover path validation, allowlisting, quotas, redaction, symlink refusal, append-only concurrency, snapshot isolation, cache retention while offline, backups, the MCP transport, both installers, and a local end-to-end sync.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md), [docs/PROVENANCE.md](docs/PROVENANCE.md), and [CONTRIBUTING.md](CONTRIBUTING.md) for more detail.

## License

Licensed under the [Apache License 2.0](LICENSE). See [docs/PROVENANCE.md](docs/PROVENANCE.md) for compatibility and attribution context.
