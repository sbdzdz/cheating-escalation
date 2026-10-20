"""Read supported review transcripts without guessing their harness format."""

import json
from pathlib import Path


def acp_entries(trial):
    steps = json.loads((trial / "trajectory.json").read_text())["steps"]
    for step in steps[1:]:
        if step.get("reasoning_content"):
            yield "THINK", step["reasoning_content"]
        if step.get("message"):
            yield "SAY", step["message"]
        results = {
            r.get("source_call_id"): r.get("content")
            for r in (step.get("observation") or {}).get("results", [])
        }
        for call in step.get("tool_calls") or []:
            yield f"TOOL {call['function_name']}", json.dumps(call.get("arguments"))
            if call["tool_call_id"] in results:
                yield "RESULT", results[call["tool_call_id"]]


def zcode_entries(trial):
    events = json.loads((trial / "transcript.json").read_text())["events"]
    buffers = {"reasoning": [], "text": []}
    for event in sorted(events, key=lambda e: e.get("seq", 0)):
        payload = event.get("payload", {})
        if event.get("type") == "model.streaming":
            kind = payload.get("kind", "")
            for name, label in (("reasoning", "THINK"), ("text", "SAY")):
                if kind == f"{name}_delta":
                    buffers[name].append(payload.get("delta", ""))
                elif kind == f"{name}_end" and buffers[name]:
                    yield label, "".join(buffers[name])
                    buffers[name] = []
        elif event.get("type") == "tool.updated":
            if payload.get("kind") == "scheduled":
                yield (
                    f"TOOL {payload.get('toolName')}",
                    json.dumps(payload.get("input")),
                )
            elif payload.get("kind") == "result":
                result = payload.get("result") or {}
                yield "RESULT", result.get("content", result)
    for name, label in (("reasoning", "THINK"), ("text", "SAY")):
        if buffers[name]:
            yield label, "".join(buffers[name])


def text_of(content):
    if isinstance(content, list):
        return "\n".join(
            part.get("text", json.dumps(part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    return content if isinstance(content, str) else json.dumps(content)


def call_entries(transcript):
    """Standard proxy log: the model's view, whichever harness ran the trial."""
    names = {}
    for call in transcript["calls"]:
        messages = call["new_messages"]
        if call["index"] == 0:
            messages = []  # Harness system prompt and the standard task prompt.
        elif call["parent"] is None:
            yield (
                "NEW THREAD",
                (
                    f"Call {call['index']} does not extend an earlier request "
                    f"({call['message_count']} messages; side call or compacted context). "
                    f"Last message:\n{text_of((messages or [{}])[-1].get('content'))}"
                ),
            )
            messages = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                name = names.get(message.get("tool_call_id"), "tool")
                yield f"RESULT {name}", text_of(message.get("content"))
            elif role in ("user", "system"):
                yield f"INJECTED {role}", text_of(message.get("content"))
        response = call["response"]
        if response.get("reasoning"):
            yield "THINK", response["reasoning"]
        if response.get("content"):
            yield "SAY", response["content"]
        for tool in response.get("tool_calls", []):
            names[tool["id"]] = tool["name"]
            yield f"TOOL {tool['name']}", tool["arguments"]
        for error in response.get("errors", []) + (
            [call["transport_error"]] if call.get("transport_error") else []
        ):
            yield "ERROR", json.dumps(error)


def kimi_entries(transcript):
    """Kimi emits chat messages and raw stdout, both needed to review tool use."""
    records = [(r["source_line"], "event", r["event"]) for r in transcript["events"]]
    records += [
        (r["source_line"], "diagnostic", r["text"])
        for r in transcript.get("diagnostics", [])
    ]
    names = {}
    for line, kind, event in sorted(records, key=lambda r: r[0]):
        if kind == "diagnostic":
            yield f"OUTPUT line {line}", event
            continue
        if not isinstance(event, dict):
            yield f"RAW line {line}", json.dumps(event)
            continue
        role = event.get("role")
        if role == "assistant":
            reasoning = event.get("reasoning_content") or event.get("reasoning")
            if reasoning:
                yield "THINK", text_of(reasoning)
            content = event.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in (
                        "think",
                        "thinking",
                        "reasoning",
                    ):
                        yield (
                            "THINK",
                            text_of(
                                part.get(
                                    "think",
                                    part.get("thinking", part.get("text", part)),
                                )
                            ),
                        )
                    else:
                        yield "SAY", text_of([part])
            elif content:
                yield "SAY", text_of(content)
            for call in event.get("tool_calls") or []:
                function = call["function"]
                names[call["id"]] = function["name"]
                yield f"TOOL {function['name']}", text_of(function.get("arguments"))
        elif role == "tool":
            name = names.get(
                event.get("tool_call_id"), event.get("tool_call_id", "tool")
            )
            yield f"RESULT {name}", text_of(event.get("content"))
        elif role in ("user", "system"):
            yield f"INJECTED {role}", text_of(event.get("content"))
        else:
            # Retain new/unknown event shapes so evidence cannot silently disappear.
            yield f"RAW line {line}", json.dumps(event)


def entries_for_trial(trial):
    """Dispatch on the declared format; old trajectory-only exports remain readable."""
    trial = Path(trial)
    path = trial / "transcript.json"
    transcript = json.loads(path.read_text()) if path.exists() else {}
    fmt = transcript.get("format")
    if fmt == "model-calls-v1":
        yield from call_entries(transcript)
    elif fmt == "kimi-code-stream-v1":
        yield from kimi_entries(transcript)
    elif fmt == "zcode-events-v1":
        yield from zcode_entries(trial)
    elif fmt in (None, "acp-events-v1") and (trial / "trajectory.json").exists():
        yield from acp_entries(trial)
    else:
        raise ValueError(f"Unsupported or missing transcript format {fmt!r} in {trial}")
    for line in transcript.get("unparsed_lines", []):
        yield "UNPARSED", line
