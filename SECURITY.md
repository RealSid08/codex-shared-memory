# Security policy

## Supported versions

Security fixes are provided for the latest `1.x` release.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/RealSid08/codex-shared-memory/security/advisories/new). Do not open a public issue for a suspected vulnerability or include real memory, credentials, hostnames, network addresses, or logs in a report.

The service is designed for one trusted user across trusted machines. SSH access to the server grants the ability to read all shared memory and create append-only notes. It is not a multi-tenant authorization system.
