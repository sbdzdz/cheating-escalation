"""Build a credential-free runtime once and stage tasks on top of it."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_BASE = ROOT / "docker/task-base.Dockerfile"
TASK_FILES = "COPY rootfs/ /\nRUN chown -R agent:agent /workspace /home/runner\nWORKDIR /workspace\n"


def runtime_spec(runtime):
    if runtime not in {"deepseek", "zcode"}:
        raise ValueError(f"Unknown prebuilt runtime: {runtime}")
    if runtime == "deepseek":
        package = ROOT / "configs/acp/deepseek-runtime"
        names = ("package.json", "package-lock.json")
        version = json.loads((package / "package.json").read_text())["dependencies"][
            "@deepseek-ai/dsh"
        ]
    else:
        package = ROOT / "configs/zcode"
        names = ("source.json",)
        version = json.loads((package / "source.json").read_text())["commit"]
    files = {name: (package / name).read_bytes() for name in names}
    recipe = (ROOT / f"docker/{runtime}-runtime.Dockerfile").read_text()
    files["Dockerfile"] = recipe.replace(
        "# TASK_BASE", TASK_BASE.read_text().rstrip()
    ).encode()
    fingerprint = hashlib.sha256(
        b"".join(k.encode() + b"\0" + v for k, v in sorted(files.items()))
    ).hexdigest()
    metadata = {
        "runtime": runtime,
        "fingerprint": fingerprint,
        "harness_version": version,
    }
    files["runtime.json"] = (json.dumps(metadata) + "\n").encode()
    return f"cheating-escalation/{runtime}:{fingerprint[:16]}", files, metadata


def ensure_runtime(runtime):
    image, files, _ = runtime_spec(runtime)
    found = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if found.returncode == 0:
        return image
    # Only these allowlisted build inputs enter Docker's context: never .env or logs.
    with tempfile.TemporaryDirectory(prefix="factorization-runtime-") as directory:
        context = Path(directory)
        for name, data in files.items():
            (context / name).write_bytes(data)
        subprocess.run(["docker", "build", "--tag", image, str(context)], check=True)
    return image


def prepare_task(task, runtime, output=None):
    """Keep source fixtures intact; use an atomic, content-addressed prepared copy."""
    task = Path(task)
    image, _, metadata = runtime_spec(runtime)
    digest = hashlib.sha256(metadata["fingerprint"].encode())
    for path in sorted(task.rglob("*")):
        if path.is_file():
            digest.update(
                str(path.relative_to(task)).encode() + b"\0" + path.read_bytes()
            )
    parent = (
        Path(output) if output else ROOT / "generated/harbor-prebuilt"
    ) / digest.hexdigest()[:16]
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / task.name
    if target.exists():
        return target
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=parent) as directory:
        staged = Path(directory) / task.name
        shutil.copytree(task, staged)
        (staged / "environment/Dockerfile").write_text(f"FROM {image}\n" + TASK_FILES)
        (staged / "runtime.json").write_text(
            json.dumps({"image": image, **metadata}, indent=2) + "\n"
        )
        try:
            os.rename(staged, target)
        except OSError:
            if not target.is_dir():
                raise
    return target
