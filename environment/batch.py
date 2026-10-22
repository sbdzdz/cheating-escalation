"""Durable experiment manifests; raw Harbor evidence stays in its original location."""

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def digest(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def files_hash(paths, base=ROOT):
    return {
        str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
        if p.is_file() and "__pycache__" not in p.parts
    }


def implementation():
    paths = []
    for directory in ("environment", "docker", "configs/acp", "configs/zcode"):
        paths.extend((ROOT / directory).rglob("*"))
    paths += [ROOT / "scripts/run_trial.py", ROOT / "uv.lock"]
    return files_hash(paths, base=ROOT)


@contextlib.contextmanager
def locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another controller owns this experiment")
        yield


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def reconcile(directory, manifest):
    for trial in manifest["trials"]:
        if trial["status"] != "running":
            continue
        receipt = directory / "receipts" / (trial["id"] + ".json")
        if receipt.exists():
            trial.update(read(receipt))
        elif not alive(trial["pid"]):
            trial["status"] = "interrupted"
    return manifest


def add_slots(manifest, target):
    if target < 1:
        raise ValueError("Target must be positive")
    for setting in manifest["settings"]:
        if manifest["settings"][setting].get("historical"):
            continue
        slots = {t["slot"] for t in manifest["trials"] if t["setting"] == setting}
        for slot in range(1, target + 1):
            if slot not in slots:
                manifest["trials"].append(
                    dict(id=uuid4().hex, setting=setting, slot=slot, status="pending")
                )


def expand_instances(task_kind, items, seeds=None):
    """Load and validate all instances before writing experiment artifacts.

    Explicit subset-sum seeds take precedence over experiment seeds. The original
    fixture is included once; only seedless custom instances are expanded.
    """
    from environment.tasks import get_task

    task = get_task(task_kind)
    if not isinstance(items, list) or not items:
        raise ValueError("instances must be a nonempty list")
    expanded = []
    for item in items:
        if isinstance(item, (str, Path)):
            item = read(ROOT / item)
        if not isinstance(item, dict):
            raise ValueError("Each instance must be a mapping or JSON file path")
        if (
            task_kind == "subset_sum"
            and not item.get("original")
            and "seed" not in item
        ):
            selected = [0] if seeds is None else seeds
            if not isinstance(selected, list) or not selected:
                raise ValueError(
                    "seeds must be a nonempty list when expanding instances"
                )
            expanded.extend(task.validate(dict(item, seed=seed)) for seed in selected)
        else:
            expanded.append(task.validate(item))
    return expanded


def prepare(config_path, directory):
    from environment.export import export_tasks
    from environment.model_config import load_profile, normalize_profile

    config = config_path if isinstance(config_path, dict) else read(config_path)
    parallel, target = config.get("parallel", 1), config.get("target_trials", 1)
    cap = config.get("max_cost_per_trial_usd", 10)
    agent_timeout = config.get("agent_timeout_sec", 3600)
    import math

    if (
        not isinstance(parallel, int)
        or parallel < 1
        or not isinstance(target, int)
        or target < 1
        or not math.isfinite(float(cap))
        or float(cap) <= 0
        or not isinstance(agent_timeout, int)
        or agent_timeout < 1
    ):
        raise ValueError("Parallel, target, cap and agent timeout must be positive")
    if "model" in config:
        profile_name, profile = config["profile"], normalize_profile(config["model"])
    else:
        profile_name, profile = load_profile(name=config["profile"])
    # Profiles contain environment references, never credential values.
    for key in profile["env"]:
        if any(
            word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
        ):
            raise ValueError("Credentials must use api_key_env, not profile env values")
    task_kind = config.get("task", "factorization")
    items = expand_instances(task_kind, config["instances"], config.get("seeds"))
    from environment.tasks import get_task

    conditions = config.get("conditions", ["baseline"])
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("conditions must be a nonempty list")
    for condition in conditions:
        get_task(task_kind).check_condition(condition)
    save(directory / "resolved-config.json", config)
    manifest = dict(
        schema_version=1,
        name=config["name"],
        parallel=parallel,
        target_trials=target,
        settings={},
        trials=[],
    )
    for instance in items:
        for condition in conditions:
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                (task,) = export_tasks(
                    task_kind,
                    tmp,
                    instance=instance,
                    condition=condition,
                    agent_timeout_sec=agent_timeout,
                )
                spec = dict(
                    task=task_kind,
                    instance=instance,
                    condition=condition,
                    profile=profile,
                    max_cost_usd=str(cap),
                    implementation=implementation(),
                    task_files=files_hash(task.rglob("*"), task),
                    instruction=(task / "instruction.md").read_text(),
                )
                fingerprint = digest(spec)
                sid = fingerprint[:16]
                if sid in manifest["settings"]:
                    if manifest["settings"][sid]["fingerprint"] != fingerprint:
                        raise ValueError("Setting hash collision")
                    raise ValueError("Duplicate setting")
                dest = directory / "settings" / sid
                import shutil

                shutil.copytree(task, dest / "task" / task.name)
                save(dest / "setting.json", spec)
                save(
                    dest / "model.json",
                    {"default": profile_name, "profiles": {profile_name: profile}},
                )
                manifest["settings"][sid] = dict(
                    fingerprint=fingerprint,
                    profile=profile_name,
                    task=str((dest / "task" / task.name).resolve()),
                    historical=False,
                )
    add_slots(manifest, target)
    save(directory / "manifest.json", manifest)
    return manifest


def check_settings(directory, manifest):
    current = implementation()
    for sid, entry in manifest["settings"].items():
        if entry.get("historical"):
            continue
        spec = read(directory / "settings" / sid / "setting.json")
        if digest(spec) != entry["fingerprint"] or spec["implementation"] != current:
            raise ValueError(
                "Implementation/configuration changed; create a new experiment"
            )
        task = Path(entry["task"])
        if files_hash(task.rglob("*"), task) != spec["task_files"]:
            raise ValueError("Snapshotted task changed")
        profile = read(directory / "settings" / sid / "model.json")["profiles"][
            entry["profile"]
        ]
        if profile != spec["profile"]:
            raise ValueError("Snapshotted model changed")


def schedule(directory, manifest):
    check_settings(directory, manifest)
    children = []
    try:
        while True:
            for child in children:
                child.poll()
            reconcile(directory, manifest)
            active = sum(t["status"] == "running" for t in manifest["trials"])
            pending = [t for t in manifest["trials"] if t["status"] == "pending"]
            for trial in pending[: max(0, manifest["parallel"] - active)]:
                check_settings(directory, manifest)
                trial["run_id"] = "batch-" + trial["id"]
                log = directory / "launcher-logs" / (trial["id"] + ".txt")
                log.parent.mkdir(exist_ok=True)
                # Persist assignment before spawning. A receipt is authoritative on resume.
                trial["status"] = "running"
                trial["pid"] = os.getpid()
                save(directory / "manifest.json", manifest)
                with log.open("a") as out:
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            str(ROOT / "scripts/run_batch.py"),
                            "action=_worker",
                            "path=" + json.dumps(str(directory)),
                            "trial=" + trial["id"],
                        ],
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                children.append(child)
                trial["pid"] = child.pid
                save(directory / "manifest.json", manifest)
            save(directory / "manifest.json", manifest)
            if not any(
                t["status"] in ("running", "pending") for t in manifest["trials"]
            ):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("Controller stopped. Active workers continue; use resume to reconnect.")
    print(Counter(t["status"] for t in manifest["trials"]))


def worker(directory, trial_id):
    manifest = read(directory / "manifest.json")
    trial = next(t for t in manifest["trials"] if t["id"] == trial_id)
    setting = manifest["settings"][trial["setting"]]
    folder = directory / "settings" / trial["setting"]
    spec = read(folder / "setting.json")
    result = dict(status="infrastructure_error")
    try:
        check_settings(directory, manifest)
        from environment.experiment_config import load_config
        from environment.trial import run_trial

        config = load_config("trial")
        config.update(
            task_path=setting["task"],
            model_snapshot=str(folder / "model.json"),
            snapshot_profile=setting["profile"],
            max_cost_usd=spec["max_cost_usd"],
            run_id=trial["run_id"],
        )
        code = run_trial(config)
        job = ROOT / "outputs/harbor" / trial["run_id"]
        result.update(returncode=code, output=str(job.relative_to(ROOT)))
        ledger = read(job / "budget.json") if (job / "budget.json").exists() else {}
        result["cost_usd"] = ledger.get("spent_usd")
        result["budget_status"] = ledger.get("status")
        # Keep errors explicit; budget termination is a finished experimental outcome.
        if ledger.get("status") == "budget_exhausted":
            result.update(status="finished", outcome="budget_exhausted")
        elif (job / "result.json").exists():
            trials = list(job.glob("trials/*/result.json"))
            errors = [read(p).get("exception_info") for p in trials]
            if code == 0 and trials and not any(errors):
                result.update(status="finished", outcome="completed")
            elif any("AgentTimeoutError" in str(e) for e in errors):
                result.update(status="finished", outcome="timeout")
            result["errors"] = errors
    except Exception as exc:
        result["error"] = str(exc)
    save(directory / "receipts" / (trial_id + ".json"), result)


def import_analysis(source, directory):
    data = read(source)
    manifest = dict(
        schema_version=1, name=directory.name, settings={}, trials=[], parallel=1
    )
    seen = set()
    for row in data["trials"]:
        (run_id,) = row["run_ids"]
        if run_id in seen:
            raise ValueError("Duplicate historical run")
        seen.add(run_id)
        spec = dict(
            model=data["model"],
            condition=data["condition"],
            number=str(row["number"]),
            bits=row["bits"],
            fermat_increments=row["fermat_increments"],
            provenance="historical; exact runtime/code fingerprint unknown",
        )
        sid = "legacy-" + digest(spec)[:16]
        manifest["settings"][sid] = dict(historical=True, **spec)
        save(directory / "settings" / sid / "setting.json", spec)
        manifest["trials"].append(
            dict(
                id=run_id,
                setting=sid,
                slot=sum(t["setting"] == sid for t in manifest["trials"]) + 1,
                status="finished",
                run_id=run_id,
                output="outputs/harbor/" + run_id,
                cost_usd=row["cost_usd"],
                historical_row=row,
            )
        )
    save(directory / "manifest.json", manifest)
    return manifest
