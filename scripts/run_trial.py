"""Run one Harbor trial configured through Hydra/YAML."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harbor_adapter.experiment_config import cli
from harbor_adapter.trial import run_trial


def main(config):
    raise SystemExit(run_trial(config))


if __name__ == "__main__":
    cli("trial", main)
