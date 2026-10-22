"""Launch, resume, inspect, retry or import an experiment with Hydra/YAML."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from environment.controller import run_batch
from environment.experiment_config import cli

if __name__ == "__main__":
    cli("batch_cli", run_batch)
