"""Compose YAML and run Hydra entry points without changing working directories."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hydra
from hydra import compose, initialize_config_dir
from hydra.core.config_store import ConfigStore
from omegaconf import MISSING, OmegaConf

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


@dataclass
class ExportConfig:
    # Defaults live in YAML; the schema validates types before export starts.
    task: str = MISSING
    instance: Any = None
    questions: list[int] = MISSING
    condition: str = MISSING
    agent_timeout_sec: int = MISSING
    output: str = MISSING


ConfigStore.instance().store(name="export_schema", node=ExportConfig)


def load_config(name, overrides=()):
    with initialize_config_dir(version_base="1.3", config_dir=str(CONFIGS)):
        cfg = compose(config_name=name, overrides=list(overrides))
    return OmegaConf.to_container(cfg, resolve=True, throw_on_missing=True)


def load_experiment(overrides=()):
    return load_config("batch", overrides)


def cli(name, callback):
    @hydra.main(version_base="1.3", config_path=str(CONFIGS), config_name=name)
    def run(cfg):
        return callback(
            OmegaConf.to_container(cfg, resolve=True, throw_on_missing=True)
        )

    return run()
