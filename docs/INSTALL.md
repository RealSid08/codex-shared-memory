# Installation

## Requirements

- Python 3.11 or newer on server and clients
- OpenSSH client and server for remote transport
- A private network path or otherwise secured SSH endpoint
- Non-interactive key authentication with host verification enabled
- Codex CLI only if the installer should register the MCP server automatically

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
python3 install_client.py \
  --machine laptop \
  --ssh-host memory-server
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

1. Copies the client script to `~/.local/share/codex-shared-memory/`.
2. Writes a private `client.json` containing local paths and the exchange command.
3. Performs the first sync. Failure stops the installer before configuration changes.
4. Registers `shared_memories` with Codex unless `--skip-codex` is used.
5. Adds or updates one marked guidance block in the selected Codex `AGENTS.md` unless `--skip-instructions` is used.
6. Creates a per-user two-minute schedule unless `--skip-scheduler` is used.

Use `--codex-home`, `--native-memory`, `--cache`, and `--install-dir` for non-default local layouts. Use `--local-data <path>` instead of `--ssh-host` for a single-machine deployment or isolated test.

Codex supports stdio MCP configuration through `config.toml` and the `codex mcp` commands. Its `AGENTS.md` hierarchy is documented separately. See the official [Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) and [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

The instruction block is what tells an agent when to consult shared memory, how to validate retrieved context, and when cross-machine writes are allowed. See [AGENT-GUIDANCE.md](AGENT-GUIDANCE.md) for the copy-paste template, placement options, and the recommended lookup workflow.

## Other MCP clients

The installer can prepare sync and cache files without changing Codex:

```sh
python3 install_client.py \
  --machine workstation \
  --ssh-host memory-server \
  --skip-codex \
  --skip-instructions
```

Then register the same stdio command in the MCP client. Example placeholders follow.

Cursor user configuration in `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "shared_memories": {
      "type": "stdio",
      "command": "ssh",
      "args": [
        "-T",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "memory-server",
        "python3 ~/.local/share/codex-shared-memory/shared_memory.py serve --data ~/.local/share/codex-shared-memory/data"
      ]
    }
  }
}
```

Enable and verify it with a fresh Cursor Agent session:

```sh
cursor-agent mcp enable shared_memories
cursor-agent mcp list-tools shared_memories
```

OpenCode user configuration in `~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "shared_memories": {
      "type": "local",
      "command": [
        "ssh",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "memory-server",
        "python3 ~/.local/share/codex-shared-memory/shared_memory.py serve --data ~/.local/share/codex-shared-memory/data"
      ],
      "enabled": true,
      "timeout": 15000
    }
  }
}
```

Start a fresh client session after changing MCP or agent instructions. Confirm tool discovery, then make real `list`, `read`, and `search` calls. A connected indicator alone does not prove the transport or server works.

## Windows notes

Run the installers in PowerShell with Python 3.11+. The client installer creates a per-user scheduled task named `CodexSharedMemorySync`; the server installer uses `CodexSharedMemoryBackup`. Pass Windows paths as quoted option values. OpenSSH must already be configured when using a remote server.

Use `--skip-scheduler` or `--skip-backup-scheduler` if organization policy blocks Task Scheduler changes.
