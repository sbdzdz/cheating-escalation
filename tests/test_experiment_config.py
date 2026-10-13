import os
import unittest

from hydra.errors import ConfigCompositionException

from harbor_adapter.experiment_config import load_experiment


class ExperimentConfigTests(unittest.TestCase):
    def test_defaults_and_large_integer_precision(self):
        cfg = load_experiment()
        self.assertEqual(len(cfg["instances"]), 11)
        row = next(r for r in cfg["instances"] if r["bits"] == 128)
        self.assertEqual(int(row["number"]), int(row["p"]) * int(row["q"]))

    def test_composition_overrides_and_no_cwd_change(self):
        cwd = os.getcwd()
        cfg = load_experiment(
            [
                "experiments=archive/pilots",
                "model=kimi-k3",
                "parallel=2",
                "target_trials=1",
            ]
        )
        self.assertEqual(cfg["profile"], "kimi-k3")
        self.assertEqual(len(cfg["instances"]), 7)
        self.assertEqual(cfg["parallel"], 2)
        self.assertEqual(cfg["target_trials"], 1)
        self.assertEqual(os.getcwd(), cwd)

    def test_typo_rejected(self):
        with self.assertRaises(ConfigCompositionException):
            load_experiment(["paralell=3"])

    def test_model_profile_fields_are_composed_and_normalized(self):
        from harbor_adapter.model_config import load_profile, normalize_profile

        cfg = load_experiment(
            ["model=deepseek-v4-flash", "model.env.DSH_REASONING_EFFORT=low"]
        )
        profile = normalize_profile(cfg["model"])
        self.assertEqual(profile["env"]["DSH_REASONING_EFFORT"], "low")
        self.assertTrue(profile["kwargs"]["registry_entry_path"].startswith("/"))
        self.assertEqual(
            load_profile(name="deepseek-v4-flash")[1]["env"]["DSH_REASONING_EFFORT"],
            "high",
        )
