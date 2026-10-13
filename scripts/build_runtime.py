"""Build the selected model profile's reusable Docker runtime (no model calls)."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harbor_adapter.model_config import DEFAULT_CONFIG, load_profile
from harbor_adapter.runtime_image import ensure_runtime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--profile", default="deepseek-v4-flash")
    args = parser.parse_args()
    _, profile = load_profile(args.config, args.profile)
    if not profile.get("runtime"):
        parser.error("This profile does not configure a prebuilt runtime")
    print(ensure_runtime(profile["runtime"]))
