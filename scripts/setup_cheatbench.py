"""Optional: fetch the pinned CheatBench source for reference; Harbor runs the task."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY = ROOT / ".deps" / "cheatbench"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    pin = json.loads((ROOT / "configs/cheatbench.json").read_text())
    DEPENDENCY.parent.mkdir(exist_ok=True)
    if not DEPENDENCY.exists():
        subprocess.run(["git", "clone", pin["repository"], str(DEPENDENCY)], check=True)
    if (
        run("git", "-C", str(DEPENDENCY), "remote", "get-url", "origin")
        != pin["repository"]
    ):
        raise SystemExit(
            "Dependency origin differs from the pinned repository; inspect it manually."
        )
    if run("git", "-C", str(DEPENDENCY), "status", "--porcelain"):
        raise SystemExit(
            "Dependency has local changes; preserve them before running setup."
        )
    if run("git", "-C", str(DEPENDENCY), "rev-parse", "HEAD") != pin["commit"]:
        subprocess.run(
            ["git", "-C", str(DEPENDENCY), "fetch", "origin", pin["commit"]], check=True
        )
        subprocess.run(
            ["git", "-C", str(DEPENDENCY), "checkout", "--detach", pin["commit"]],
            check=True,
        )
    print(f"CheatBench {pin['commit']} available at {DEPENDENCY}")


if __name__ == "__main__":
    main()
