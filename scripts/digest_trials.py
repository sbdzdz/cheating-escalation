"""Write per-trial review digests using Hydra configuration."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harbor_adapter.digests import digest as digest
from harbor_adapter.digests import write_digests
from harbor_adapter.experiment_config import cli

if __name__ == "__main__":
    cli("digest", write_digests)
