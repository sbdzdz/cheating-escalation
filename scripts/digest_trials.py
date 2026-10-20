"""Write per-trial review digests: the trace without harness boilerplate, unannotated."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harbor_adapter.transcripts import entries_for_trial


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
            return [
                4,
                5,
                7,
                8,
                9,
                10,
                11,
                16,
                18,
                21,
                22,
                23,
                26,
                27,
                30,
                31,
                32,
                35,
                36,
                37,
                44,
                45,
                46,
                47,
                50,
                51,
                53,
                55,
                57,
                59,
            ]
        from tasks.subset_sum.instances import generate

        return generate(instance)[1]
    return [str(instance["p"]), str(instance["q"])]


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
        "(Known initial setup messages are omitted for model-call and ACP trajectories. "
        "Kimi records include raw output and diagnostics in source order.)"
    )
    lines.append("")
    entries = entries_for_trial(trial)
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
    parser.add_argument(
        "--no-reasoning", action="store_true", help="Leave out THINK entries"
    )
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
        spec = json.loads(
            (directory / "settings" / trial["setting"] / "setting.json").read_text()
        )
        (folder,) = (ROOT / trial["output"] / "trials").iterdir()
        path = args.output / f"{trial['id'][:8]}.md"
        path.write_text(
            digest(folder, spec, trial.get("outcome"), not args.no_reasoning)
        )
        index.append(
            dict(
                id=trial["id"],
                run_id=trial["run_id"],
                condition=spec["condition"],
                instance=spec["instance"],
                digest=str(path),
                transcript=str(folder),
            )
        )
    (args.output / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"{len(index)} digests in {args.output}")


if __name__ == "__main__":
    main()
