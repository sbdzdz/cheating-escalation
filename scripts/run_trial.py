"""Run one trial of an exported task with Harbor's Docker backend."""

import argparse
import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harbor_adapter.conditions import CONDITIONS
from harbor_adapter.model_config import DEFAULT_CONFIG, load_profile
from harbor_adapter.outputs import compact_job
from harbor_adapter.tasks import TASKS, resolve_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance", type=Path, help="Custom instance JSON used for export"
    )
    parser.add_argument("--condition", choices=CONDITIONS, default="baseline")
    parser.add_argument("--question", type=int, default=4)
    parser.add_argument("--task", choices=TASKS, default="factorization")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Model profile YAML or saved batch JSON",
    )
    parser.add_argument("--profile", help="Profile name; otherwise uses config default")
    parser.add_argument(
        "--agent",
        choices=["oracle", "nop"],
        help="Docker plumbing check without a model: submit the planted answer, or do nothing",
    )
    parser.add_argument(
        "--model", help="Override the selected profile model identifier"
    )
    parser.add_argument(
        "--agent-version", help="Override the profile's harness version"
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Validate job configuration without Docker or API calls",
    )
    parser.add_argument(
        "--keep-raw-outputs",
        action="store_true",
        help="Keep debug/ uncompressed after the run",
    )
    parser.add_argument(
        "--max-cost-usd",
        help="Stop new OpenRouter requests after this reported cost (one-request overshoot possible)",
    )
    parser.add_argument(
        "--task-path", type=Path, help="Use a batch-snapshotted exported task"
    )
    parser.add_argument(
        "--run-id", help="Explicit unique output ID assigned by batch runner"
    )
    args = parser.parse_args()
    try:
        profile_name, profile = load_profile(args.config, args.profile)
        if args.agent and args.profile:
            parser.error("Use --profile or --agent, not both")
        if args.agent:
            profile_name = args.agent
            profile = {
                "agent": args.agent,
                "model": None,
                "env": {},
                "kwargs": {},
                "api_key_env": None,
                "key_target": None,
                "url_target": None,
            }
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    if args.model:
        profile["model"] = args.model
    if args.agent_version:
        if "registry_entry_path" in profile["kwargs"]:
            parser.error("Set the ACP harness version in its registry config")
        profile["kwargs"]["version"] = args.agent_version
    cap = None
    if args.max_cost_usd is not None:
        try:
            cap = Decimal(args.max_cost_usd)
            if not cap.is_finite() or cap <= 0:
                raise ValueError()
        except (InvalidOperation, ValueError):
            parser.error("--max-cost-usd must be finite and positive")
        if not profile["url_target"]:
            parser.error("--max-cost-usd requires an OpenRouter model profile")
    try:
        task = resolve_task(
            args.task,
            question=args.question,
            instance=args.instance,
            condition=args.condition,
            task_path=args.task_path,
        )
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    if not (task / "task.toml").exists():
        parser.error(f"Export the selected task first; expected task.toml in {task}")
    load_dotenv(ROOT / ".env")
    if (
        args.max_cost_usd
        and profile["env"].get(profile["url_target"], "").rstrip("/")
        != "https://openrouter.ai/api/v1"
    ):
        parser.error("--max-cost-usd requires the OpenRouter endpoint")
    if not args.print_config:
        try:
            subprocess.run(
                ["docker", "info"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise SystemExit(
                "Docker is unavailable. Start Docker Desktop or another Docker-compatible daemon, then retry."
            )
    if profile.get("runtime"):
        from harbor_adapter.runtime_image import ensure_runtime, prepare_task

        if not args.print_config:
            ensure_runtime(profile["runtime"])
        task = prepare_task(task, profile["runtime"])
        profile["env"]["FACTORIZATION_PREBUILT_RUNTIME"] = profile["runtime"]
    run_id = ("budget-" if args.max_cost_usd else "run-") + uuid4().hex
    if args.run_id:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
            parser.error("Invalid run ID")
        run_id = args.run_id
    job = ROOT / "outputs/harbor" / run_id
    if job.exists() and not args.print_config:
        parser.error(f"Output already exists: {job}")
    command = [
        str(Path(sys.executable).parent / "harbor"),
        "run",
        "--path",
        str(task),
        "--agent",
        profile["agent"],
        "--env",
        "docker",
        "--n-concurrent",
        "1",
        "--n-attempts",
        "1",
        "--max-retries",
        "0",
        "--jobs-dir",
        str(job),
        "--job-name",
        "debug",
    ]
    if profile.get("setup_timeout_multiplier"):
        command += [
            "--agent-setup-timeout-multiplier",
            str(profile["setup_timeout_multiplier"]),
        ]
    if profile["model"]:
        command += ["--model", profile["model"]]
    for key, value in profile["kwargs"].items():
        command += ["--ak", f"{key}={value}"]
    for key, value in profile["env"].items():
        command += ["--ae", f"{key}={value}"]
    key_env = profile["api_key_env"]
    key_target, url_target = profile["key_target"], profile["url_target"]
    if key_env:
        if not args.print_config and not os.environ.get(key_env):
            parser.error(f"Set {key_env} in .env or the shell")
        command += ["--ae", f"{key_target}=${{{key_env}}}"]
    os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
    if args.print_config:
        command.append("--print-config")
    if args.max_cost_usd:
        # The agent receives a run-scoped proxy token, never the real API key.
        key_arg = command.index(f"{key_target}=${{{key_env}}}")
        command[key_arg] = f"{key_target}=${{BUDGET_PROXY_TOKEN}}"
        url_arg = next(
            i for i, value in enumerate(command) if value.startswith(url_target + "=")
        )
        if args.print_config:
            command[url_arg] = url_target + "=http://host.docker.internal:PORT/v1"
            print(
                f"Per-run cap: ${cap}; serialized, post-request accounting.",
                file=sys.stderr,
            )
        else:
            sys.path.insert(0, str(ROOT))
            from harbor_adapter.budget_proxy import BudgetProxy

            ledger = job / "budget.json"
            with BudgetProxy(os.environ[key_env], cap, ledger) as proxy:
                command[url_arg] = url_target + "=" + proxy.url
                child_env = dict(os.environ)
                child_env.pop(key_env, None)
                child_env.pop(key_target, None)
                child_env["BUDGET_PROXY_TOKEN"] = proxy.token
                print(f"Budget ledger: {ledger}", flush=True)
                result = subprocess.run(command, env=child_env)
                print(
                    f"Budget status: {proxy.budget.status}; reported spend: ${proxy.budget.spent}"
                )
            compact_job(job, keep_debug=args.keep_raw_outputs)
            raise SystemExit(result.returncode)
    if args.print_config:
        os.execv(command[0], command)
    result = subprocess.run(command)
    compact_job(job, keep_debug=args.keep_raw_outputs)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
