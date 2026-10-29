# SPDX-License-Identifier: Apache-2.0
"""Self-hosted shared Markdown memory for coding-agent harnesses.

Python 3.11+, standard library only. Modules:

- core: limits, path safety, redaction, atomic writes
- sources: per-harness readers for native memory (codex, claude-code, markdown)
- store: server-side SQLite store, schema migration, generated index views
- tools: MCP tool schemas and list/read/search/add_ad_hoc_note behavior
- mcp: newline-delimited JSON-RPC stdio transport
- server: exchange protocol handler (v1 and v2)
- client: client sync, local cache, cache-backed MCP backend
- harnesses: MCP registration and guidance for Codex, Claude Code, OpenCode, Cursor
- scheduler: launchd, systemd and Task Scheduler definitions
- install: client and server installers
- cli: command-line entry point
"""

VERSION = "2.0.0"
