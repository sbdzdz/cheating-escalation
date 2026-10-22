"""Resolve Harbor model profiles without reading or serializing credentials."""

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/model/deepseek-v4-flash.yaml"


def load_profile(path=DEFAULT_CONFIG, name=None):
    path = Path(path).resolve()
    if path.suffix in (".yaml", ".yml"):
        from omegaconf import OmegaConf

        if name and path == DEFAULT_CONFIG.resolve():
            if (
                Path(name).name != name
                or not (ROOT / "configs/model" / (name + ".yaml")).is_file()
            ):
                raise ValueError(f"Unknown model profile {name!r}")
            path = ROOT / "configs/model" / (name + ".yaml")
        config = OmegaConf.to_container(
            OmegaConf.load(path), resolve=True, throw_on_missing=True
        )
        if name and name != config["profile"]:
            raise ValueError(f"Unknown model profile {name!r} in {path}")
        name, profile = config["profile"], config["model"]
    else:
        # Existing batch snapshots remain readable.
        config = json.loads(path.read_text())
        name = name or config["default"]
        if name not in config["profiles"]:
            raise ValueError(f"Unknown model profile {name!r}")
        profile = config["profiles"][name]
    return name, normalize_profile(profile)


def normalize_profile(profile):
    profile = copy.deepcopy(profile)
    for key in (
        "agent",
        "model",
        "kwargs",
        "env",
        "api_key_env",
        "key_target",
        "url_target",
    ):
        if key not in profile:
            raise ValueError(f"Profile is missing {key}")
    registry = profile["kwargs"].get("registry_entry_path")
    if registry:
        # Registry paths are relative to the project root, like exported task paths.
        registry = (ROOT / registry).resolve()
        if not registry.is_file():
            raise ValueError(f"Missing ACP registry entry: {registry}")
        profile["kwargs"]["registry_entry_path"] = str(registry)
    return profile


def resolve_profile(config):
    """Saved snapshots take precedence over the current YAML model selection."""
    if config.get("model_snapshot"):
        return load_profile(config["model_snapshot"], config.get("snapshot_profile"))
    if config.get("snapshot_profile"):
        raise ValueError("snapshot_profile requires model_snapshot")
    return config["profile"], normalize_profile(config["model"])
