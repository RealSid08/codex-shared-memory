# Operations

## Health checks

On the server, use the exact script and data paths printed by `install_server.py`:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py status \
  --data ~/.local/share/codex-shared-memory/data
```

The result reports SQLite integrity, enrolled machine IDs with last successful sync timestamps, file count, and free bytes.

On a client, run the configured sync command or:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py sync \
  --config ~/.local/share/codex-shared-memory/client.json
```

Inspect `status.json` in the configured cache for the last success. A failed sync preserves the existing cache and writes `error.json`; the next success removes the error file.

## Backups

Run a backup manually with the same data, mount, and free-space options as the server installation:

```sh
python3 ~/.local/share/codex-shared-memory/shared_memory.py backup \
  --data ~/.local/share/codex-shared-memory/data
```

Backups are integrity-checked SQLite copies under `<data>/backups/`. The service retains three dated recovery points. They are on the same storage device by default, so copy verified backups elsewhere if device failure is in scope.

## Restore

1. Stop client sync schedules and close clients using this MCP.
2. Stop the server backup schedule.
3. Preserve the current database together with any WAL and SHM files for diagnosis.
4. Restore a verified backup as `memory.sqlite3` with user-only permissions.
5. Do not leave stale WAL or SHM files beside the restored database.
6. Run `status`, then re-enable schedules and clients.
7. Let each machine republish its current native snapshot.

## Forget and delete

Append-only notes support corrections, not secure erasure. An actual deletion requires administrative work:

1. Stop sync and MCP use.
2. Remove the fact from every originating native memory through the source product's supported controls.
3. Delete the corresponding canonical SQLite rows or rebuild the store from reviewed snapshots.
4. Remove affected backups and every client cache.
5. Resume sync and verify that the content does not return.

The MCP intentionally exposes no delete tool. A correction note does not erase older content.

## Disconnect a client

1. Disable its schedule.
2. Remove the `shared_memories` MCP entry from the client.
3. Remove the marked shared-memory block from `AGENTS.md` or equivalent client instructions.
4. Keep or remove the local cache and runtime configuration according to your retention needs.

Common schedule identifiers are:

- macOS client: `codex-shared-memory.sync`
- macOS server backup: `codex-shared-memory.backup`
- Linux client: `codex-shared-memory-sync.timer`
- Linux server backup: `codex-shared-memory-backup.timer`
- Windows client: `CodexSharedMemorySync`
- Windows server backup: `CodexSharedMemoryBackup`
