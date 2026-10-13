"""Combine reviewed complexity batches without double-counting shared settings."""

import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def summarize(trials):
    groups = defaultdict(list)
    for trial in trials:
        groups[(trial["bits"], trial["fermat_increments"])].append(trial)
    levels = []
    for (bits, increments), rows in sorted(groups.items()):
        assert len({r["number"] for r in rows}) == 1
        levels.append(
            dict(
                bits=bits,
                fermat_increments=increments,
                number=rows[0]["number"],
                n=len(rows),
                sources=dict(Counter(r["classification"]["source"] for r in rows)),
                observed_attempts={
                    k: sum(r["classification"][k] for r in rows) for k in "ABC"
                },
                manual_evidence=dict(
                    Counter(r["classification"]["manual_evidence"] for r in rows)
                ),
                cost_usd=str(sum(Decimal(r["cost_usd"]) for r in rows)),
            )
        )
    ids = [r["run_ids"][0] for r in trials]
    assert len(ids) == len(set(ids)), "Duplicate runs"
    return dict(
        model="deepseek/deepseek-v4-flash",
        condition="baseline",
        n=len(trials),
        total_cost_usd=str(sum(Decimal(r["cost_usd"]) for r in trials)),
        levels=levels,
        trials=trials,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=OUT / "experiments/complexity-sweep-historical/manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT / "deepseek-complexity-combined-analysis.json",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    trials = []
    models, conditions = set(), set()
    replaced = {t["retry_of"] for t in manifest["trials"] if t.get("retry_of")}
    for trial in manifest["trials"]:
        if trial["id"] in replaced:
            continue
        if trial.get("historical_row"):
            row = trial["historical_row"]
            setting = manifest["settings"][trial["setting"]]
            models.add(setting["model"])
            conditions.add(setting["condition"])
        else:
            if trial["status"] != "finished":
                raise ValueError(
                    "Resolve unfinished/error trials explicitly before aggregation"
                )
            setting = json.loads(
                (
                    args.manifest.parent
                    / "settings"
                    / trial["setting"]
                    / "setting.json"
                ).read_text()
            )
            models.add(setting["profile"]["model"])
            conditions.add(setting["condition"])
            job = ROOT / trial["output"]
            (trajectory,) = job.glob("trials/*/trajectory.json")
            classification = json.loads(
                (trajectory.parent / "classification.json").read_text()
            )
            n, p, q = (setting["instance"][k] for k in ("number", "p", "q"))
            from math import isqrt

            row = dict(
                number=str(n),
                bits=n.bit_length(),
                fermat_increments=(p + q) // 2 - isqrt(n) - (isqrt(n) ** 2 != n),
                classification=classification,
                trajectory=str(trajectory.relative_to(ROOT)),
                run_ids=[trial["run_id"]],
                cost_usd=trial["cost_usd"],
                verifier=json.loads((trajectory.parent / "verifier.json").read_text()),
            )
        trials.append(row)
    if len(models) != 1 or len(conditions) != 1:
        raise ValueError("Complexity report requires a single model and condition")
    result = summarize(trials)
    result.update(model=models.pop(), condition=conditions.pop())
    if replaced:
        result["excluded_retry_attempts"] = [
            t for t in manifest["trials"] if t["id"] in replaced
        ]
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for level in result["levels"]:
        print(level["bits"], level["fermat_increments"], level["n"], level["sources"])


if __name__ == "__main__":
    main()
