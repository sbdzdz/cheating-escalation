"""Compose batch YAML without Hydra launching jobs or changing directories."""

from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def load_experiment(overrides=()):
    with initialize_config_dir(version_base="1.3", config_dir=str(CONFIGS)):
        cfg = compose(config_name="batch", overrides=list(overrides))
    return OmegaConf.to_container(cfg, resolve=True, throw_on_missing=True)
