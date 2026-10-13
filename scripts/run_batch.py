"""Launch, resume, inspect, or import a factorization experiment."""

import argparse
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["start", "resume", "status", "retry", "import", "_worker"]
    )
    parser.add_argument(
        "path", type=Path, nargs="?", help="Experiment directory (not needed for start)"
    )
    parser.add_argument(
        "--output", type=Path, help="Experiment directory for start/import"
    )
    parser.add_argument("--parallel", type=int)
    parser.add_argument("--target-trials", type=int)
    parser.add_argument("--trial", help="Explicit failed trial to replace")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare/inspect without launching evaluations",
    )
    # Strip Hydra overrides before argparse so positionals remain unambiguous.
    overrides = [arg for arg in sys.argv[1:] if "=" in arg and not arg.startswith("--")]
    args = parser.parse_args([arg for arg in sys.argv[1:] if arg not in overrides])
    config = None
    if args.action == "start":
        if args.path:
            parser.error(
                "Use experiments=complexity-sweep to select YAML configuration"
            )
        from harbor_adapter.experiment_config import load_experiment

        config = load_experiment(overrides)
        if args.parallel is not None:
            config["parallel"] = args.parallel
        if args.target_trials is not None:
            config["target_trials"] = args.target_trials
    elif overrides:
        parser.error("Hydra overrides apply only to start; resume uses saved settings")
    elif args.path is None:
        parser.error("An experiment directory or import file is required")
    if args.action == "_worker":
        worker(args.path.resolve(), args.trial)
        return
    if args.action in ("start", "import"):
        if args.output:
            directory = args.output.resolve()
        elif args.action == "start":
            name = config["name"]
            if Path(name).name != name or name in (".", ".."):
                parser.error("Experiment name must be a directory name")
            directory = ROOT / "outputs/experiments" / name
        else:
            parser.error("import requires --output")
    else:
        directory = args.path.resolve()
    with locked(directory):
        manifest_path = directory / "manifest.json"
        if args.action in ("start", "import"):
            if manifest_path.exists():
                parser.error("Experiment exists; use resume or a new output directory")
            manifest = (
                prepare(config, directory)
                if args.action == "start"
                else import_analysis(args.path, directory)
            )
        else:
            manifest = reconcile(directory, read(manifest_path))
        if args.parallel is not None:
            if args.parallel < 1:
                parser.error("Parallel must be positive")
            manifest["parallel"] = args.parallel
        if args.target_trials is not None:
            if any(s.get("historical") for s in manifest["settings"].values()):
                parser.error(
                    "Historical settings cannot schedule new trials; start a new experiment"
                )
            add_slots(manifest, args.target_trials)
            manifest["target_trials"] = args.target_trials
        if args.action == "retry":
            old = next((t for t in manifest["trials"] if t["id"] == args.trial), None)
            if not old or old["status"] not in ("interrupted", "infrastructure_error"):
                parser.error(
                    "Specify an interrupted or infrastructure_error trial with --trial"
                )
            if any(t.get("retry_of") == old["id"] for t in manifest["trials"]):
                parser.error("This trial already has a replacement")
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


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(str(exc))
