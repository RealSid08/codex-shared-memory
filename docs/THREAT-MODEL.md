# Threat model

## Intended use

One person operates the server and enrolls only trusted machines. The service shares concise Markdown reference data over local stdio or authenticated SSH. The server is not exposed as a public HTTP service.

## Trust boundaries

- SSH authenticates transport peers and protects traffic in transit.
- Every enrolled SSH identity has the same effective read access to all shared memory.
- The MCP client and model can call every exposed tool. Client-side confirmation and policy remain important for the write tool.
- Native memory files are untrusted reference content, not executable instructions.

## Safeguards

- Strict source allowlist and visible relative-path validation
- Symlink refusal for source roots, source files, cache parents, and store roots
- Per-file, per-machine, total-store, file-count, and wire-size quotas
- Best-effort redaction of common tokens, private keys, and credential-assignment lines
- Rejection of suspicious explicit notes instead of silent modification
- SQLite transactions for snapshot isolation and append-only uniqueness
- Optional required-mount guard and configurable minimum free space
- Private file creation through a process umask and database mode enforcement
- No offline write queue and no agent-facing delete capability

## Important limitations

- Secret detection can miss credentials written in prose or an unfamiliar format.
- A compromised enrolled client or SSH identity can read all shared content and add notes.
- This is not multi-tenant. It has no per-machine read policy or per-note authorization.
- SSH server configuration, key lifecycle, operating-system security, full-disk encryption, and off-device backups are outside this repository.
- Cache refresh is atomic per file, not across the entire directory.
- SQLite backups on the same disk do not protect against disk loss.
- Generated memory can contain sensitive personal or project facts even when it contains no credential.

Do not expose the stdio process through an unauthenticated network wrapper. If multiple untrusted users or organizations need access, use a different architecture with explicit identity, authorization, audit, retention, and deletion controls.
