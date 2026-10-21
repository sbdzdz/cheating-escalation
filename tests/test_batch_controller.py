import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harbor_adapter.batch import read, save
from harbor_adapter.controller import run_batch
from harbor_adapter.experiment_config import load_config

ROOT = Path(__file__).resolve().parents[1]


class BatchControllerTests(unittest.TestCase):
    def test_cli_start_status_and_resume_preserve_saved_settings(self):
        with tempfile.TemporaryDirectory(prefix="batch = ") as tmp:
            directory = Path(tmp).resolve() / "experiment"

            def command(*overrides):
                return subprocess.run(
                    [sys.executable, str(ROOT / "scripts/run_batch.py"), *overrides],
                    capture_output=True,
                    text=True,
                    check=True,
                )

            command(
                "action=start",
                "experiments=smoke",
                "parallel=3",
                "target_trials=2",
                "agent_timeout_sec=300",
                f'output="{directory}"',
                "dry_run=true",
            )
            original = read(directory / "manifest.json")
            self.assertEqual(original["parallel"], 3)
            self.assertEqual(len(original["trials"]), 2)
            command("action=status", f'path="{directory}"')
            command("action=resume", f'path="{directory}"', "dry_run=true")
            self.assertEqual(read(directory / "manifest.json"), original)
            command(
                "action=resume",
                f'path="{directory}"',
                "parallel=4",
                "target_trials=3",
                "dry_run=true",
            )
            updated = read(directory / "manifest.json")
            self.assertEqual(updated["parallel"], 4)
            self.assertEqual(updated["target_trials"], 3)
            self.assertEqual(updated["trials"][:2], original["trials"])
            self.assertEqual(len(updated["trials"]), 3)

    def test_retry_keeps_original_trial_and_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            save(
                directory / "manifest.json",
                {
                    "settings": {"s": {}},
                    "parallel": 1,
                    "target_trials": 1,
                    "trials": [
                        {
                            "id": "failed",
                            "setting": "s",
                            "slot": 1,
                            "status": "infrastructure_error",
                        }
                    ],
                },
            )
            cfg = load_config(
                "batch_cli",
                [
                    "action=retry",
                    "path=" + str(directory),
                    "trial=failed",
                    "dry_run=true",
                ],
            )
            with (
                patch("harbor_adapter.controller.check_settings"),
                patch("harbor_adapter.controller.schedule") as schedule,
            ):
                run_batch(cfg)
                schedule.assert_not_called()
                with self.assertRaisesRegex(ValueError, "already has a replacement"):
                    run_batch(cfg)
            trials = read(directory / "manifest.json")["trials"]
            self.assertEqual(len(trials), 2)
            self.assertEqual(trials[0]["status"], "infrastructure_error")
            self.assertEqual(trials[1]["retry_of"], "failed")
            self.assertEqual(trials[1]["slot"], 1)

    def test_import_and_invalid_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "analysis.json"
            save(
                source,
                {
                    "model": "legacy",
                    "condition": "baseline",
                    "trials": [
                        {
                            "run_ids": ["old"],
                            "number": "15",
                            "bits": 4,
                            "fermat_increments": 0,
                            "cost_usd": "0.1",
                        }
                    ],
                },
            )
            output = root / "imported"
            run_batch(
                load_config(
                    "batch_cli",
                    ["action=import", "path=" + str(source), "output=" + str(output)],
                )
            )
            manifest = read(output / "manifest.json")
            self.assertTrue(next(iter(manifest["settings"].values()))["historical"])
            cfg = load_config(
                "batch_cli", ["action=status", "path=" + str(output), "parallel=3"]
            )
            with self.assertRaisesRegex(ValueError, "only supported"):
                run_batch(cfg)
            self.assertEqual(read(output / "manifest.json"), manifest)
            cfg = load_config(
                "batch_cli",
                ["action=resume", "path=" + str(root / "missing"), "dry_run=true"],
            )
            with self.assertRaisesRegex(ValueError, "No experiment manifest"):
                run_batch(cfg)
            self.assertFalse((root / "missing").exists())
