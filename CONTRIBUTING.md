# Contributing

The runtime intentionally uses only the Python standard library. Keep changes small, portable, and compatible with Python 3.11 or newer.

Before opening a change:

```sh
uv sync --locked
uv run ruff check .
uv run python -m unittest discover -s tests -v
uv run python scripts/release_check.py
```

Tests must use synthetic content and temporary directories. Never attach a real memory snapshot, runtime configuration, database, cache, SSH log, home-directory path, tailnet address, host key, token, or credential to an issue or pull request.

Security reports should not be filed publicly until a private reporting channel is chosen. See `SECURITY.md`.
