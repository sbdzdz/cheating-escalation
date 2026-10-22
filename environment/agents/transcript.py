"""Convert Kimi's mixed CLI output into a single JSON document."""

import json
from pathlib import Path


def export_transcript(source: Path) -> Path:
    target = source.with_suffix(".json")
    events = []
    diagnostics = []
    for line_number, line in enumerate(source.read_text().splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            diagnostics.append({"source_line": line_number, "text": line})
        else:
            events.append({"source_line": line_number, "event": event})
    document = {
        "format": "kimi-code-stream-v1",
        "events": events,
        "diagnostics": diagnostics,
    }
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(target)
    source.unlink()
    return target


if __name__ == "__main__":
    import sys

    source = Path(sys.argv[1])
    if source.exists():
        export_transcript(source)
