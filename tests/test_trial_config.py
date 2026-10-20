import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hydra.errors import ConfigCompositionException

from harbor_adapter.batch import read, save, worker
from harbor_adapter.experiment_config import load_config
from harbor_adapter.model_config import load_profile, resolve_profile
from harbor_adapter.trial import run_trial
from scripts.build_runtime import main as build_runtime

ROOT = Path(__file__).resolve().parents[1]


class TrialConfigTests(unittest.TestCase):
    def test_shared_model_defaults_and_typed_overrides(self):
        for command in ("trial", "runtime"):
            cfg = load_config(command)
            self.assertEqual(cfg["profile"], "deepseek-v4-flash")
            self.assertEqual(resolve_profile(cfg), load_profile())
        cfg = load_config(
            "trial",
            ["model=kimi-k3", "model.kwargs.version=0.43.0", "print_config=true"],
        )
        self.assertEqual(resolve_profile(cfg)[1]["kwargs"]["version"], "0.43.0")
        self.assertTrue(cfg["print_config"])
        for override in ("question=bad", "print_config=bad", "max_cost_uds=3"):
            with (
                self.subTest(override=override),
                self.assertRaises(ConfigCompositionException),
            ):
                load_config("trial", [override])

    def test_composed_model_settings_reach_harbor(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/run_trial.py"),
                "model=deepseek-v4-flash",
                "model.env.DSH_REASONING_EFFORT=low",
                "max_cost_usd=3",
                "print_config=true",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        agent = json.loads(result.stdout)["agents"][0]
        self.assertEqual(agent["env"]["DSH_REASONING_EFFORT"], "low")
        self.assertEqual(agent["env"]["DEEPSEEK_API_KEY"], "${BUDGET_PROXY_TOKEN}")

    def test_saved_profile_takes_precedence_over_current_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            _, profile = load_profile(name="kimi-k3")
            profile["model"] = "saved/provider-model"
            save(path, {"default": "saved", "profiles": {"saved": profile}})
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_trial.py"),
                    "model=deepseek-v4-flash",
                    "model_snapshot=" + str(path),
                    "snapshot_profile=saved",
                    "print_config=true",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                json.loads(result.stdout)["agents"][0]["model_name"],
                "saved/provider-model",
            )
            cfg = load_config("trial", ["snapshot_profile=saved"])
            with self.assertRaisesRegex(ValueError, "requires model_snapshot"):
                resolve_profile(cfg)

    def test_invalid_budget_rejected_before_docker(self):
        for value in ("0", "-1", "NaN", "Infinity"):
            with (
                self.subTest(value=value),
                patch("harbor_adapter.trial.subprocess.run") as run,
            ):
                cfg = load_config("trial", ["max_cost_usd=" + value])
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    run_trial(cfg)
                run.assert_not_called()

    def test_runtime_build_uses_composed_profile(self):
        with (
            patch(
                "scripts.build_runtime.ensure_runtime", return_value="image"
            ) as build,
            patch("builtins.print"),
        ):
            build_runtime(load_config("runtime", ["model=glm-5.3-flash"]))
            build.assert_called_once_with("zcode")
            with self.assertRaisesRegex(ValueError, "does not configure"):
                build_runtime(load_config("runtime", ["model=kimi-k3"]))
            self.assertEqual(build.call_count, 1)

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
                patch("harbor_adapter.batch.ROOT", root),
                patch("harbor_adapter.batch.check_settings"),
                patch("harbor_adapter.trial.run_trial", return_value=0) as run,
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
