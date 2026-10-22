"""Aggregate a reviewed batch using Hydra configuration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harbor_adapter.experiment_config import cli
from trajectory_review.summaries import summarize as summarize
from trajectory_review.summaries import write_summary

if __name__ == "__main__":
    cli("summary", write_summary)
