import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from environment.batch import read, save, worker
from environment.experiment_config import load_config
from environment.model_config import load_profile, resolve_profile
from environment.trial import run_trial


class TrialTests(unittest.TestCase):
    def test_invalid_budget_rejected_before_docker(self):
        for value in ("0", "-1", "NaN", "Infinity"):
            with (
                self.subTest(value=value),
                patch("environment.trial.subprocess.run") as run,
            ):
                cfg = load_config("trial", ["max_cost_usd=" + value])
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    run_trial(cfg)
                run.assert_not_called()

    def test_worker_uses_saved_profile_and_writes_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "experiment"
            folder = directory / "settings/s"
            _, profile = load_profile(name="kimi-k3")
            save(
                folder / "model.json",
                {"default": "saved", "profiles": {"saved": profile}},
            )
            save(folder / "setting.json", {"max_cost_usd": "2.50"})
            save(
                directory / "manifest.json",
                {
                    "settings": {
                        "s": {"task": str(folder / "task"), "profile": "saved"}
                    },
                    "trials": [
                        {"id": "trial", "setting": "s", "run_id": "batch-trial"}
                    ],
                },
            )
            job = root / "outputs/harbor/batch-trial"
            save(job / "result.json", {})
            save(job / "trials/t/result.json", {"exception_info": None})
            save(job / "budget.json", {"spent_usd": "0.1", "status": "available"})
            with (
                patch("environment.batch.ROOT", root),
                patch("environment.batch.check_settings"),
                patch("environment.trial.run_trial", return_value=0) as run,
            ):
                worker(directory, "trial")
            cfg = run.call_args.args[0]
            self.assertEqual(resolve_profile(cfg), ("saved", profile))
            self.assertEqual(cfg["max_cost_usd"], "2.50")
            self.assertEqual(cfg["run_id"], "batch-trial")
            self.assertEqual(cfg["task_path"], str(folder / "task"))
            receipt = read(directory / "receipts/trial.json")
            self.assertEqual(receipt["outcome"], "completed")
            self.assertEqual(receipt["cost_usd"], "0.1")
