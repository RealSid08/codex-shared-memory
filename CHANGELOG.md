# Changelog

## 1.0.0 - 2026-09-12

- Extract the proven single-user service into a portable repository.
- Replace hard-coded host, username, data path, mount, and scheduler identifiers with options and safe defaults.
- Add server and client installers for local or SSH-backed deployments.
- Preserve the allowlisted snapshot model, append-only notes, offline cache, quotas, redaction, backups, and stdio MCP interface.
- Add cross-platform CI, installer coverage, release checks, architecture, operations, installation, and threat-model documentation.
- Exclude all private snapshots, runtime configuration, databases, credentials, network details, and logs.
