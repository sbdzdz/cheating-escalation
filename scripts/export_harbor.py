"""Build original CheatBench instances and export independent Harbor tasks."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harbor_adapter.conditions import (
    CONDITIONS,
    RETAINED_RECORDS,
    TASK_CONDITION_PROMPTS,
)
from harbor_adapter.runtime_image import TASK_BASE, TASK_FILES
from harbor_adapter.tasks import TASKS, get_task


def export(
    row,
    output,
    condition="baseline",
    *,
    source=None,
    task_kind="factorization",
    agent_timeout_sec=3600,
):
    definition = get_task(task_kind)
    definition.check_condition(condition)
    task = definition.harbor
    source = source or task.HERE
    prompts = TASK_CONDITION_PROMPTS[task_kind]
    fields = task.PUBLIC_FIELDS
    if condition not in CONDITIONS:
        raise ValueError(f"Unknown condition: {condition}")
    name = row["name"] if condition == "baseline" else row["name"] + "__" + condition
    target = output / name
    # Generated task directories are disposable; never overwrite unknown content.
    if target.exists():
        if not (target / ".generated-by-export_harbor").exists():
            raise ValueError(f"Refusing to overwrite unrecognized directory: {target}")
        shutil.rmtree(target)
    env = target / "environment"
    rootfs = env / "rootfs"
    sidecar = env / "verifier"
    tests = target / "tests"
    for path in (rootfs, sidecar, tests):
        path.mkdir(parents=True, exist_ok=True)
    source_root = source
    for absolute, mapping in ((False, row["files"]), (True, row["files_abs"])):
        for destination, source in mapping.items():
            relative = (
                Path(destination.lstrip("/"))
                if absolute
                else Path("workspace") / destination
            )
            if ".." in relative.parts:
                raise ValueError(f"Invalid staging path: {destination}")
            dest = rootfs / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / "environment" / source, dest)
    instruction = row["input"]
    if condition in prompts:
        instruction += "\n\n" + prompts[condition]
    (target / "instruction.md").write_text(instruction)
    (target / "condition.json").write_text(
        json.dumps(
            {
                "condition": condition,
                "synthetic_history": condition in RETAINED_RECORDS
                or condition == "b-shown",
            },
            indent=2,
        )
        + "\n"
    )
    (target / "instance-metadata.json").write_text(
        json.dumps(
            {"task": task_kind, **{k: row[k] for k in fields}, **row["meta"]}, indent=2
        )
        + "\n"
    )
    (target / ".generated-by-export_harbor").touch()
    for name in ("UPSTREAM.md",):
        shutil.copyfile(task.HERE / name, target / name)
    for directory in (sidecar, tests):
        (directory / "instance.json").write_text(
            json.dumps({k: row[k] for k in fields})
        )
    shutil.copyfile(task.HERE / "grader.py", sidecar / "grader.py")
    shutil.copyfile(ROOT / "harbor_adapter/server.py", sidecar / "server.py")
    shutil.copyfile(ROOT / "harbor_adapter/verify.py", tests / "verify.py")
    (env / "Dockerfile").write_text(TASK_BASE.read_text() + TASK_FILES)
    (sidecar / "Dockerfile").write_text("""FROM python:3.12-slim
RUN pip install --no-cache-dir mcp==1.30.0
WORKDIR /app
COPY grader.py server.py instance.json ./
CMD ["python", "server.py"]
""")
    (env / "docker-compose.yaml").write_text("""services:
  main:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      verifier:
        condition: service_healthy
  verifier:
    build:
      context: ./verifier
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; socket.create_connection(('127.0.0.1',8000),2).close()"]
      interval: 2s
      timeout: 3s
      retries: 30
""")
    (tests / "Dockerfile").write_text("""FROM python:3.12-slim
COPY . /tests/
""")
    (tests / "test.sh").write_text("#!/bin/sh\nset -eu\npython /tests/verify.py\n")
    solution = target / "solution"
    solution.mkdir()
    # Oracle is a plumbing check, deliberately reading the planted answer key.
    # Harbor only uploads solution/ for oracle runs, never model runs.
    (solution / "solve.sh").write_text("""#!/bin/sh
set -eu
pip install --quiet --target /tmp/oracle-libs mcp==1.30.0
PYTHONPATH=/tmp/oracle-libs python /solution/solve.py
""")
    (solution / "solve.py").write_text(task.oracle(row))
    (target / "task.toml").write_text(f"""schema_version = "1.3"
source = "{task.SOURCE}"

[[artifacts]]
source = "/evidence/state.json"
service = "verifier"

[agent]
timeout_sec = {agent_timeout_sec}
user = "agent"

[environment]
workdir = "/workspace"

[[environment.mcp_servers]]
name = "verifier"
transport = "streamable-http"
url = "http://verifier:8000/mcp"

[verifier]
timeout_sec = 60
environment_mode = "separate"

[verifier.environment]
network_mode = "public"
""")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance",
        type=Path,
        help="Instance JSON: number, p, q (4–256-bit odd semiprime) or subset-sum parameters",
    )
    parser.add_argument("--condition", choices=CONDITIONS, default="baseline")
    parser.add_argument("--agent-timeout-sec", type=int, default=3600)
    parser.add_argument("--questions", nargs="+", type=int, default=[4])
    parser.add_argument("--output", type=Path, default=ROOT / "generated/harbor")
    parser.add_argument("--task", choices=TASKS, default="factorization")
    args = parser.parse_args()
    task = get_task(args.task)
    try:
        task.check_condition(args.condition)
        instance = json.loads(args.instance.read_text()) if args.instance else None
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            for row in task.build(source, args.questions, instance):
                print(
                    export(
                        row,
                        args.output.resolve(),
                        args.condition,
                        source=source,
                        task_kind=args.task,
                        agent_timeout_sec=args.agent_timeout_sec,
                    )
                )
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
