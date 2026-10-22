"""Build the configured model's reusable Docker runtime (no model calls)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from environment.experiment_config import cli
from environment.model_config import resolve_profile
from environment.runtime_image import ensure_runtime


def main(config):
    _, profile = resolve_profile(config)
    if not profile.get("runtime"):
        raise ValueError("This profile does not configure a prebuilt runtime")
    print(ensure_runtime(profile["runtime"]))


if __name__ == "__main__":
    cli("runtime", main)
