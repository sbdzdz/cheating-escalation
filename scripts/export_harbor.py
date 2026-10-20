"""Export independent Harbor tasks configured through Hydra/YAML."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harbor_adapter.experiment_config import cli
from harbor_adapter.export import export, export_tasks

# Preserve imports used by external scripts; reusable implementation lives in the adapter.
__all__ = ["export", "export_tasks"]


def main(config):
    for path in export_tasks(**config):
        print(path)


if __name__ == "__main__":
    cli("export", main)
