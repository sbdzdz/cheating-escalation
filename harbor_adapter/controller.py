"""Batch lifecycle operations driven by composed configuration."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from harbor_adapter.batch import (
    add_slots,
    check_settings,
    import_analysis,
    locked,
    prepare,
    read,
    reconcile,
    save,
    schedule,
    worker,
)

ROOT = Path(__file__).resolve().parents[1]


def run_batch(config):
    args = SimpleNamespace(**config)
    if args.action not in ("start", "resume", "status", "retry", "import", "_worker"):
        raise ValueError(f"Unknown action: {args.action}")
    args.path = Path(args.path) if args.path is not None else None
    args.output = Path(args.output) if args.output is not None else None
    if args.action == "start" and args.path is not None:
        raise ValueError("Use experiments=... to select a new experiment")
    if args.action != "start" and args.path is None:
        raise ValueError("path=... must specify an experiment directory or import file")
    if args.output is not None and args.action not in ("start", "import"):
        raise ValueError("output is only supported for start and import")
    if args.action in ("retry", "_worker") and not args.trial:
        raise ValueError("trial=... is required")
    if args.trial is not None and args.action not in ("retry", "_worker"):
        raise ValueError("trial is only supported for retry and _worker")
    for name in ("parallel", "target_trials"):
        value = getattr(args, name)
        if value is not None:
            if args.action not in ("start", "resume", "retry"):
                raise ValueError(
                    f"{name} is only supported for start, resume and retry"
                )
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
    if args.action == "_worker":
        worker(args.path.resolve(), args.trial)
        return
    if args.action in ("start", "import"):
        if args.output:
            directory = args.output.resolve()
        elif args.action == "start":
            name = config["name"]
            if Path(name).name != name or name in (".", ".."):
                raise ValueError("Experiment name must be a directory name")
            directory = ROOT / "outputs/experiments" / name
        else:
            raise ValueError("import requires output=...")
    else:
        directory = args.path.resolve()
    if (
        args.action not in ("start", "import")
        and not (directory / "manifest.json").is_file()
    ):
        raise ValueError(f"No experiment manifest in {directory}")
    with locked(directory):
        manifest_path = directory / "manifest.json"
        if args.action in ("start", "import"):
            if manifest_path.exists():
                raise ValueError(
                    "Experiment exists; use resume or a new output directory"
                )
            manifest = (
                prepare(
                    {
                        k: v
                        for k, v in config.items()
                        if k not in {"action", "path", "output", "trial", "dry_run"}
                    },
                    directory,
                )
                if args.action == "start"
                else import_analysis(args.path, directory)
            )
        else:
            manifest = reconcile(directory, read(manifest_path))
            if args.action in ("resume", "retry"):
                check_settings(directory, manifest)
        if args.parallel is not None and args.action != "start":
            if args.parallel < 1:
                raise ValueError("Parallel must be positive")
            manifest["parallel"] = args.parallel
        if args.target_trials is not None and args.action != "start":
            if any(s.get("historical") for s in manifest["settings"].values()):
                raise ValueError(
                    "Historical settings cannot schedule new trials; start a new experiment"
                )
            add_slots(manifest, args.target_trials)
            manifest["target_trials"] = args.target_trials
        if args.action == "retry":
            old = next((t for t in manifest["trials"] if t["id"] == args.trial), None)
            if not old or old["status"] not in ("interrupted", "infrastructure_error"):
                raise ValueError(
                    "Specify an interrupted or infrastructure_error trial with trial=..."
                )
            if any(t.get("retry_of") == old["id"] for t in manifest["trials"]):
                raise ValueError("This trial already has a replacement")
            manifest["trials"].append(
                dict(
                    id=uuid4().hex,
                    setting=old["setting"],
                    slot=old["slot"],
                    status="pending",
                    retry_of=old["id"],
                )
            )
        save(manifest_path, manifest)
        print(
            f"{directory}: {len(manifest['settings'])} settings; {dict(Counter(t['status'] for t in manifest['trials']))}"
        )
        if args.action == "status":
            from decimal import Decimal

            for sid in manifest["settings"]:
                rows = [t for t in manifest["trials"] if t["setting"] == sid]
                spent = sum(
                    (
                        Decimal(str(t["cost_usd"]))
                        for t in rows
                        if t.get("cost_usd") is not None
                    ),
                    Decimal(0),
                )
                print(
                    f"  {sid}: {dict(Counter(t['status'] for t in rows))}; reported ${spent}"
                )
        if args.action in ("start", "resume", "retry") and not args.dry_run:
            schedule(directory, manifest)
        elif args.action in ("start", "resume"):
            check_settings(directory, manifest)
