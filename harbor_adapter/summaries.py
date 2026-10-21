"""Combine reviewed complexity batches without double-counting shared settings."""

import json
from collections import Counter, defaultdict
from decimal import Decimal
from math import isqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(trials, *, task, model, condition):
    if task not in {"factorization", "subset_sum"}:
        raise ValueError(f"Unsupported task: {task}")
    keys = (
        ("bits", "fermat_increments")
        if task == "factorization"
        else ("bits", "set_size", "solution_size")
    )
    groups = defaultdict(list)
    for trial in trials:
        groups[tuple(trial[k] for k in keys)].append(trial)
    levels = []
    for values, rows in sorted(groups.items()):
        dimensions = dict(zip(keys, values))
        if task == "factorization":
            numbers = sorted({r["number"] for r in rows})
            dimensions.update(
                {"number": numbers[0]} if len(numbers) == 1 else {"numbers": numbers}
            )
        levels.append(
            dict(
                **dimensions,
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
    ids = [run_id for r in trials for run_id in r["run_ids"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate runs")
    return dict(
        task=task,
        model=model,
        condition=condition,
        n=len(trials),
        total_cost_usd=str(sum(Decimal(r["cost_usd"]) for r in trials)),
        levels=levels,
        trials=trials,
    )


def write_summary(config):
    manifest_path = Path(config["manifest"])
    output = Path(config["output"])
    manifest = json.loads(manifest_path.read_text())
    trials = []
    models, conditions, tasks = set(), set(), set()
    replaced = {t["retry_of"] for t in manifest["trials"] if t.get("retry_of")}
    for trial in manifest["trials"]:
        if trial["id"] in replaced:
            continue
        if trial["status"] != "finished":
            raise ValueError(
                "Resolve unfinished/error trials explicitly before aggregation"
            )
        if trial.get("historical_row"):
            row = trial["historical_row"]
            setting = manifest["settings"][trial["setting"]]
            models.add(setting["model"])
            conditions.add(setting["condition"])
        else:
            setting = json.loads(
                (
                    manifest_path.parent
                    / "settings"
                    / trial["setting"]
                    / "setting.json"
                ).read_text()
            )
            models.add(setting["profile"]["model"])
            conditions.add(setting["condition"])
            job = ROOT / trial["output"]
            (folder,) = job.glob("trials/*/")
            # Standard model-call transcripts replace harness trajectories in new runs.
            trajectory = next(
                folder / name
                for name in ("trajectory.json", "transcript.json")
                if (folder / name).exists()
            )
            classification = json.loads(
                (trajectory.parent / "classification.json").read_text()
            )
            instance = setting["instance"]
            if setting["task"] == "factorization":
                n, p, q = (int(instance[k]) for k in ("number", "p", "q"))
                dimensions = dict(
                    number=str(n),
                    bits=n.bit_length(),
                    fermat_increments=(p + q) // 2 - isqrt(n) - (isqrt(n) ** 2 != n),
                )
            elif setting["task"] == "subset_sum":
                if instance.get("original"):
                    raise ValueError(
                        "Subset-sum complexity reports require generated instances with explicit dimensions"
                    )
                from tasks.subset_sum.instances import validate

                parameters = validate(instance)
                dimensions = {
                    k: parameters[k] for k in ("bits", "set_size", "solution_size")
                }
            else:
                raise ValueError(f"Unsupported task: {setting['task']}")
            row = dict(
                **dimensions,
                instance=instance,
                classification=classification,
                trajectory=str(
                    trajectory.relative_to(ROOT)
                    if trajectory.is_relative_to(ROOT)
                    else trajectory
                ),
                run_ids=[trial["run_id"]],
                cost_usd=trial["cost_usd"],
                verifier=json.loads((trajectory.parent / "verifier.json").read_text()),
            )
        tasks.add(setting.get("task", "factorization"))
        trials.append(row)
    if len(models) != 1 or len(conditions) != 1 or len(tasks) != 1:
        raise ValueError(
            "Complexity report requires a single task, model and condition"
        )
    result = summarize(
        trials, task=tasks.pop(), model=models.pop(), condition=conditions.pop()
    )
    if replaced:
        result["excluded_retry_attempts"] = [
            t for t in manifest["trials"] if t["id"] in replaced
        ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['n']} trials in {output}")
    return result
