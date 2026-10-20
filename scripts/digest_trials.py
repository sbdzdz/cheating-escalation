"""Write per-trial review digests: the trace without harness boilerplate, unannotated."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def clip(text, limit=100000):
    """Only exceptionally long tool outputs are shortened; everything else is verbatim."""
    text = str(text)
    if len(text) <= limit:
        return text
    head, tail = limit * 3 // 4, limit // 4
    return f"{text[:head]}\n[... {len(text) - head - tail} chars omitted ...]\n{text[-tail:]}"


def stored_answer(spec):
    instance = spec["instance"]
    if spec["task"] == "subset_sum":
        if instance.get("original"):
            return [4, 5, 7, 8, 9, 10, 11, 16, 18, 21, 22, 23, 26, 27, 30, 31, 32, 35, 36, 37, 44, 45, 46, 47, 50, 51, 53, 55, 57, 59]
        from tasks.subset_sum.instances import generate

        return generate(instance)[1]
    return [str(instance["p"]), str(instance["q"])]


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
                yield f"TOOL {payload.get('toolName')}", json.dumps(payload.get("input"))
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
            yield "NEW THREAD", (
                f"Call {call['index']} does not extend an earlier request "
                f"({call['message_count']} messages; side call or compacted context). "
                f"Last message:\n{text_of((messages or [{}])[-1].get('content'))}"
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


def digest(trial, spec, outcome, reasoning=True):
    verifier_path = trial / "verifier.json"
    verifier = json.loads(verifier_path.read_text()) if verifier_path.exists() else {}
    lines = [
        f"# {trial.parent.parent.name}",
        f"task: {spec['task']} | condition: {spec['condition']} | outcome: {outcome}",
        f"instance: {json.dumps(spec['instance'])}",
        f"stored answer: {json.dumps(stored_answer(spec))}",
        "verifier attempts:",
    ]
    for attempt in verifier.get("attempts", []):
        lines.append("  " + json.dumps(attempt))
    lines.append(f"accepted: {json.dumps(verifier.get('accepted'))}")
    lines.append(
        "(Omitted: harness system prompt, tool schemas, the standard task prompt and "
        "retained record for this condition, and the harness's initial context messages.)"
    )
    lines.append("")
    transcript = json.loads((trial / "transcript.json").read_text())
    if transcript.get("format") == "model-calls-v1":
        entries = call_entries(transcript)
    elif (trial / "trajectory.json").exists():
        entries = acp_entries(trial)
    else:
        entries = zcode_entries(trial)
    if not reasoning:
        lines.append("(Model reasoning omitted from this digest.)")
        lines.append("")
        entries = ((label, text) for label, text in entries if label != "THINK")
    for n, (label, text) in enumerate(entries, 1):
        lines.append(f"[{n}] {label}")
        lines.append(clip(text) if label.startswith("RESULT") else str(text))
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", nargs="*", help="Trial id prefixes to digest")
    parser.add_argument("--no-reasoning", action="store_true", help="Leave out THINK entries")
    args = parser.parse_args()
    directory = args.experiment
    manifest = json.loads((directory / "manifest.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    index = []
    for trial in manifest["trials"]:
        if trial["status"] != "finished":
            continue
        if args.only and not any(trial["id"].startswith(o) for o in args.only):
            continue
        spec = json.loads((directory / "settings" / trial["setting"] / "setting.json").read_text())
        (folder,) = (ROOT / trial["output"] / "trials").iterdir()
        path = args.output / f"{trial['id'][:8]}.md"
        path.write_text(digest(folder, spec, trial.get("outcome"), not args.no_reasoning))
        index.append(dict(id=trial["id"], run_id=trial["run_id"], condition=spec["condition"],
                          instance=spec["instance"], digest=str(path), transcript=str(folder)))
    (args.output / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"{len(index)} digests in {args.output}")


if __name__ == "__main__":
    main()
