"""Compose YAML and run Hydra entry points without changing working directories."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hydra
from hydra import compose, initialize_config_dir
from hydra.core.config_store import ConfigStore
from hydra.core.global_hydra import GlobalHydra
from omegaconf import MISSING, OmegaConf

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


@dataclass
class DigestConfig:
    experiment: str = MISSING
    output: str = MISSING
    only: list[str] = MISSING
    reasoning: bool = MISSING
    result_limit: int = MISSING


@dataclass
class ExportConfig:
    # Defaults live in YAML; the schema validates types before export starts.
    task: str = MISSING
    instance: Any = None
    questions: list[int] = MISSING
    condition: str = MISSING
    agent_timeout_sec: int = MISSING
    output: str = MISSING


@dataclass
class RuntimeConfig:
    profile: str = MISSING
    model: dict[str, Any] = MISSING
    model_snapshot: str | None = None
    snapshot_profile: str | None = None


@dataclass
class TrialConfig(RuntimeConfig):
    task: str = MISSING
    instance: Any = None
    question: int = MISSING
    condition: str = MISSING
    agent: str | None = None
    print_config: bool = MISSING
    keep_raw_outputs: bool = MISSING
    max_cost_usd: str | None = None
    task_path: str | None = None
    run_id: str | None = None
    output: str = MISSING


@dataclass
class BatchControllerConfig:
    action: str = MISSING
    path: str | None = None
    output: str | None = None
    trial: str | None = None
    dry_run: bool = MISSING
    parallel: int | None = None
    target_trials: int | None = None


@dataclass
class BatchStartConfig(BatchControllerConfig):
    profile: str = MISSING
    model: dict[str, Any] = MISSING
    name: str = MISSING
    description: str | None = None
    task: str = MISSING
    conditions: list[str] = MISSING
    instances: list[Any] = MISSING
    seeds: list[int] | None = None
    max_cost_per_trial_usd: str = MISSING
    agent_timeout_sec: int = MISSING


ConfigStore.instance().store(name="batch_controller_schema", node=BatchControllerConfig)
ConfigStore.instance().store(name="batch_start_schema", node=BatchStartConfig)
ConfigStore.instance().store(name="runtime_schema", node=RuntimeConfig)
ConfigStore.instance().store(name="trial_schema", node=TrialConfig)

ConfigStore.instance().store(name="export_schema", node=ExportConfig)
ConfigStore.instance().store(name="digest_schema", node=DigestConfig)


def load_config(name, overrides=()):
    if GlobalHydra.instance().is_initialized():
        cfg = compose(config_name=name, overrides=list(overrides))
    else:
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
