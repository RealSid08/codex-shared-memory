# SPDX-License-Identifier: Apache-2.0
"""Exchange protocol handler run on the server (locally or over SSH).

Requests arrive as one JSON object on stdin:

- v1 (legacy clients): {"machine", "files"} -> stored as the machine's codex source
- v2 sync: {"protocol": 2, "op": "sync", "machine",
            "sources": {name: {"type", "files"}}}
- v2 note: {"protocol": 2, "op": "note", "filename", "note"}

Sync responses always include {"ingest", "files"} so v1 clients keep working. v1
clients reject any response file over their 512 KiB limit, so their view omits those.
"""

import re

from . import VERSION
from .core import MACHINE_RE

V1_MAX_FILE = 512 * 1024


def handle(store, request):
    if not isinstance(request, dict):
        raise TypeError("Exchange request must be a JSON object")
    protocol = request.get("protocol", 1)
    op = request.get("op", "sync")
    if protocol == 1:
        ingest = store.ingest(request["machine"], request["files"])
        files = {
            path: content
            for path, content in store.all_files().items()
            if len(content.encode("utf-8")) <= V1_MAX_FILE
        }
        return {"ingest": ingest, "files": files}
    if protocol != 2:
        raise ValueError(f"Unsupported exchange protocol {protocol}")
    if op == "note":
        store.add_note(request["filename"], request["note"])
        return {"protocol": 2, "server_version": VERSION, "note": "created"}
    if op != "sync":
        raise ValueError(f"Unknown exchange operation {op}")
    sources = request["sources"]
    if not isinstance(sources, dict):
        raise TypeError("sources must be an object")
    if sources:
        ingest = store.ingest_many(
            request["machine"],
            {name: (spec["type"], spec["files"]) for name, spec in sources.items()},
        )
    else:  # every local source failed: still return the shared view
        if not re.fullmatch(MACHINE_RE, str(request["machine"])):
            raise ValueError("Invalid machine ID")
        ingest = {"machine": request["machine"], "sources": {}}
    removed = []
    if "enabled" in request:
        removed = store.prune(request["machine"], request["enabled"])
    return {
        "protocol": 2,
        "server_version": VERSION,
        "ingest": ingest,
        "removed_sources": removed,
        "files": store.all_files(),
    }
