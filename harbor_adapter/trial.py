"""Execute one configured Harbor trial; shared by the CLI and batch workers."""

import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from dotenv import load_dotenv

from harbor_adapter.model_config import resolve_profile
from harbor_adapter.outputs import compact_job
from harbor_adapter.tasks import resolve_task

ROOT = Path(__file__).resolve().parents[1]


def run_trial(config):
    args = SimpleNamespace(**config)
    if args.agent is not None:
        if args.agent not in ("oracle", "nop"):
            raise ValueError(
                "agent must be oracle, nop, or null for the configured model"
            )
        if args.model_snapshot:
            raise ValueError("agent and model_snapshot cannot be combined")
        profile = dict(
            agent=args.agent,
            model=None,
            env={},
            kwargs={},
            api_key_env=None,
            key_target=None,
            url_target=None,
        )
    else:
        _, profile = resolve_profile(config)
    cap = None
    if args.max_cost_usd is not None:
        try:
            cap = Decimal(args.max_cost_usd)
            if not cap.is_finite() or cap <= 0:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValueError("max_cost_usd must be finite and positive")
        if not profile["url_target"]:
            raise ValueError("max_cost_usd requires an OpenRouter model profile")
    task = resolve_task(
        args.task,
        question=args.question,
        instance=args.instance,
        condition=args.condition,
        task_path=args.task_path,
    )
    if not (task / "task.toml").exists():
        raise ValueError(
            f"Export the selected task first; expected task.toml in {task}"
        )
    load_dotenv(ROOT / ".env")
    if (
        args.max_cost_usd
        and profile["env"].get(profile["url_target"], "").rstrip("/")
        != "https://openrouter.ai/api/v1"
    ):
        raise ValueError("max_cost_usd requires the OpenRouter endpoint")
    if not args.print_config:
        try:
            subprocess.run(
                ["docker", "info"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            raise RuntimeError(
                "Docker is unavailable. Start Docker Desktop or another Docker-compatible daemon, then retry."
            )
    if profile.get("runtime"):
        from harbor_adapter.runtime_image import ensure_runtime, prepare_task

        if not args.print_config:
            ensure_runtime(profile["runtime"])
        task = prepare_task(task, profile["runtime"])
        profile["env"]["EXPERIMENT_PREBUILT_RUNTIME"] = profile["runtime"]
    run_id = ("budget-" if args.max_cost_usd else "run-") + uuid4().hex
    if args.run_id:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
            raise ValueError("Invalid run ID")
        run_id = args.run_id
    job = (ROOT / args.output).resolve() / run_id
    if job.exists() and not args.print_config:
        raise ValueError(f"Output already exists: {job}")
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
            raise ValueError(f"Set {key_env} in .env or the shell")
        command += ["--ae", f"{key_target}=${{{key_env}}}"]
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = str(ROOT) + os.pathsep + child_env.get("PYTHONPATH", "")
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
            from harbor_adapter.budget_proxy import BudgetProxy

            ledger = job / "budget.json"
            with BudgetProxy(os.environ[key_env], cap, ledger) as proxy:
                command[url_arg] = url_target + "=" + proxy.url
                child_env.pop(key_env, None)
                child_env.pop(key_target, None)
                child_env["BUDGET_PROXY_TOKEN"] = proxy.token
                print(f"Budget ledger: {ledger}", flush=True)
                result = subprocess.run(command, env=child_env)
                print(
                    f"Budget status: {proxy.budget.status}; reported spend: ${proxy.budget.spent}"
                )
            compact_job(job, keep_debug=args.keep_raw_outputs)
            return result.returncode
    result = subprocess.run(command, env=child_env)
    if not args.print_config:
        compact_job(job, keep_debug=args.keep_raw_outputs)
    return result.returncode
