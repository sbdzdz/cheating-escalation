"""Write per-trial review digests using Hydra configuration."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trajectory_review.digests import digest as digest
from trajectory_review.digests import write_digests
from environment.experiment_config import cli

if __name__ == "__main__":
    cli("digest", write_digests)
