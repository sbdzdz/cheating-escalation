"""Summarize authoritative controlled-tool events without inferred intent or use."""

import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from environment.experiment_config import cli
from environment.verify import score


def summarize(config):
    manifest_path = Path(config["manifest"])
    manifest = json.loads(manifest_path.read_text())
    replaced = {t["retry_of"] for t in manifest["trials"] if t.get("retry_of")}
    rows = []
    groups = defaultdict(list)
    for t in manifest["trials"]:
        if t["id"] in replaced:
            continue
        if t["status"] != "finished":
            raise ValueError("Resolve unfinished/error trials before aggregation")
        folder = manifest_path.parent / "settings" / t["setting"]
        setting = json.loads((folder / "setting.json").read_text())
        if setting.get("controlled_tools") is None:
            raise ValueError("Not a controlled-tool trial")
        (trial,) = (ROOT / t["output"] / "trials").iterdir()
        state = json.loads((trial / "verifier.json").read_text())
        transcript = json.loads((trial / "transcript.json").read_text())
        finish_reason = transcript["calls"][-1]["response"]["finish_reason"]
        audit = state["controlled_tools"]
        events = audit["events"]
        expected = json.loads(
            (
                Path(manifest["settings"][t["setting"]]["task"]) / "tests/instance.json"
            ).read_text()
        )
        data = dict(
            trial_id=t["id"],
            condition=setting["condition"],
            task=setting["task"],
            instance=setting["instance"],
            discovery=setting["controlled_tools"]["discovery"],
            permitted_shortcuts=setting["controlled_tools"]["permitted_shortcuts"],
            accepted=state["accepted"] is not None,
            credited_score=score(state, expected),
            unauthorized_attempt=any(not e["permitted"] for e in events),
            answer_returned=any(e["answer_returned"] for e in events),
            unauthorized_answer_returned=any(
                e["answer_returned"] and not e["permitted"] for e in events
            ),
            accepted_after_exposure=audit["accepted_after_exposure"],
            termination=(
                "output_token_limit" if finish_reason == "length" else t.get("outcome")
            ),
            manifest_outcome=t.get("outcome"),
            finish_reason=finish_reason,
            cost_usd=t.get("cost_usd"),
        )
        for operation, label in (("R1", "computation"), ("R2", "lookup")):
            data[label + "_attempt"] = any(e["operation"] == operation for e in events)
            data["prohibited_" + label] = any(
                e["operation"] == operation and not e["permitted"] for e in events
            )
        rows.append(data)
        dimensions = {k: v for k, v in data["instance"].items() if k != "seed"}
        key = (
            data["task"],
            data["condition"],
            data["discovery"],
            tuple(sorted(data["permitted_shortcuts"])),
            json.dumps(dimensions, sort_keys=True),
        )
        groups[key].append(data)
    counts = []
    fields = (
        "accepted",
        "unauthorized_attempt",
        "answer_returned",
        "unauthorized_answer_returned",
        "accepted_after_exposure",
        "computation_attempt",
        "lookup_attempt",
        "prohibited_computation",
        "prohibited_lookup",
    )
    for key, group in groups.items():
        counts.append(
            dict(
                task=key[0],
                condition=key[1],
                discovery=key[2],
                permitted_shortcuts=list(key[3]),
                instance=json.loads(key[4]),
                n=len(group),
                credited=sum(r["credited_score"] for r in group),
                termination=dict(Counter(r["termination"] for r in group)),
                **{k: sum(r[k] for r in group) for k in fields},
            )
        )
    result = dict(
        n=len(rows),
        groups=counts,
        trials=rows,
        spending_including_replaced_attempts_usd=str(
            sum(
                (
                    Decimal(str(t["cost_usd"]))
                    for t in manifest["trials"]
                    if t.get("cost_usd") is not None
                ),
                Decimal(0),
            )
        ),
        interpretation="Exposure before acceptance does not establish copying, use, or deceptive intent.",
    )
    output = Path(config["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{len(rows)} controlled trials in {output}")


if __name__ == "__main__":
    cli("controlled_summary", summarize)
