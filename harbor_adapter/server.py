"""Interactive verifier; only this sidecar owns authoritative score state."""

import json
import os
import threading
from pathlib import Path

from grader import DESCRIPTION, make_tool
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult


def create_server(row, evidence_path):
    state, check = make_tool(row, {}, "/workspace")
    lock = threading.Lock()
    evidence_path = Path(evidence_path)

    def save():
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = evidence_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(evidence_path)

    save()
    server = FastMCP("verifier", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

    def submit(args):
        with lock:
            result = check(args)
            save()
            return CallToolResult.model_validate(result)

    if "numbers" in row:

        @server.tool(name="verify_subset", description=DESCRIPTION)
        def verify_subset(subset_indices: list[int]) -> CallToolResult:
            return submit({"subset_indices": subset_indices})

    else:

        @server.tool(name="verify_factors", description=DESCRIPTION)
        def verify_factors(p: str, q: str) -> CallToolResult:
            return submit({"p": p, "q": q})

    return server


if __name__ == "__main__":
    row = json.loads(Path("/app/instance.json").read_text())
    create_server(row, "/evidence/state.json").run(transport="streamable-http")
