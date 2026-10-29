# Installation

## Requirements

- Python 3.11 or newer on server and clients
- OpenSSH client and server for remote transport
- A private network path or otherwise secured SSH endpoint
- Non-interactive key authentication with host verification enabled
- The CLI of each harness to register automatically (`codex`, `claude`); OpenCode and Cursor are configured through their JSON files

The runtime has no third-party Python dependencies.

## 1. Install the server

Clone or copy this repository onto the server, then run:

```sh
python3 install_server.py
```

This copies `shared_memory.py` to `~/.local/share/codex-shared-memory/`, initializes `~/.local/share/codex-shared-memory/data/`, and schedules daily backups for the signed-in user.

If the data must stay on a mounted disk, use both options:

```sh
python3 install_server.py \
  --data-dir /srv/shared-memory/data \
  --require-mount /srv/shared-memory \
  --min-free-bytes 1073741824
```

The mount guard refuses to open the store if the required mount disappears or if the data directory is outside it. The free-space threshold refuses new writes before the disk becomes critically full.

Use `--skip-backup-scheduler` when the host uses another scheduler. The installer prints exact `serve_command`, `exchange_command`, and data paths and records them in the private runtime file `server.json`.

## 2. Prepare SSH

Create or reuse an SSH host alias on each client. Verify the server's host key out of band. Confirm that this succeeds without a password prompt:

```sh
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes memory-server true
```

Do not disable host-key checking. An enrolled SSH identity is trusted to read the entire shared store and create notes, so do not enroll shared or untrusted machines.


## 3. Install a client

Clone or copy this repository onto the client. Choose a stable lowercase machine ID:

```sh
python3 install_client.py --machine laptop --ssh-host memory-server
```

The defaults expect the remote script and data at:

```text
~/.local/share/codex-shared-memory/shared_memory.py
~/.local/share/codex-shared-memory/data
```

Override a custom server deployment explicitly:

```sh
python3 install_client.py \
  --machine laptop \
  --ssh-host memory-server \
  --remote-script /opt/codex-shared-memory/shared_memory.py \
  --remote-data /srv/shared-memory/data \
  --remote-require-mount /srv/shared-memory \
  --min-free-bytes 1073741824
```

The installer:

1. Copies `shared_memory.py` and the `sharedmem/` package to `~/.local/share/codex-shared-memory/`.
2. Resolves memory sources (see below) and writes a private `client.json`.
3. Performs the first sync. Failure stops the installer before any harness configuration changes.
4. Registers `shared_memories` with each selected harness (see below) unless `--skip-mcp` is used.
5. Adds or updates one marked guidance block in each harness's global instructions unless `--skip-instructions` is used. Symlinked instruction files are written once; a file that already has its own shared-memory policy is left unchanged.
6. Creates a per-user two-minute schedule unless `--skip-scheduler` is used.

Use `--codex-home`, `--cache`, and `--install-dir` for non-default local layouts. Use `--local-data <path>` instead of `--ssh-host` for a single-machine deployment or isolated test.

### Memory sources

By default the installer enables every source whose directory exists:

- `codex`: `$CODEX_HOME/memories` (or `--native-memory`)
- `claude-code`: `~/.claude/projects`

Choose explicitly with `--source codex`, `--source claude-code=/other/path`, and add plain Markdown directories with `--markdown team=/path/to/notes`. Rerun the installer to change sources; the server keeps each source's last snapshot until the machine republishes it.

### Harnesses

`--harness` selects integrations (repeatable); by default every detected harness is configured:

| Harness | MCP registration | Guidance |
|---|---|---|
| `codex` | `codex mcp add shared_memories` (honors `CODEX_HOME`) | `$CODEX_HOME/AGENTS.md` |
| `claude-code` | `claude mcp add --scope user shared_memories` | `~/.claude/CLAUDE.md` |
| `opencode` | `mcp.shared_memories` in `~/.config/opencode/opencode.json` | `~/.config/opencode/AGENTS.md` |
| `cursor` | `mcpServers.shared_memories` in `~/.cursor/mcp.json` | `~/.cursor/AGENTS.md`, if present |

The registered command is `python3 ~/.local/share/codex-shared-memory/shared_memory.py serve --config <client.json>`, which serves reads from the local cache. Use `--mcp-mode remote` to register the SSH server command instead. JSON configs are backed up once as `*.before-shared-memory`; a JSONC file with comments is refused so it can be edited by hand.

For any other stdio MCP client, register the same `serve --config` command under the name `shared_memories` and copy the block from [AGENT-GUIDANCE.md](AGENT-GUIDANCE.md) into its instructions.

### Verify

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py doctor \
  --config ~/.local/share/codex-shared-memory/client.json
```

`doctor` checks every source, a live server status call, cache freshness and the last error, and whether each harness points `shared_memories` at this client. Then start a fresh agent session and make real `list`, `read`, and `search` calls.

## Windows notes

Run the installers in PowerShell with Python 3.11+. The client installer creates a per-user scheduled task named `CodexSharedMemorySync`; the server installer uses `CodexSharedMemoryBackup`. Pass Windows paths as quoted option values. OpenSSH must already be configured when using a remote server.

Use `--skip-scheduler` or `--skip-backup-scheduler` if organization policy blocks Task Scheduler changes.
