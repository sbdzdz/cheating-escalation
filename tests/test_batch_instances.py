"""Batch inputs are validated before export and seed expansion is explicit."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harbor_adapter.batch import check_settings, expand_instances, prepare, read, save


class BatchInstanceTests(unittest.TestCase):
    def test_seed_precedence_defaults_and_original_fixture(self):
        items = [
            {"bits": 16, "set_size": 8},
            {"bits": 16, "set_size": 8, "seed": 7},
            {"original": True},
        ]
        before = copy.deepcopy(items)
        expanded = expand_instances("subset_sum", items, [1, 2])
        self.assertEqual([item.get("seed") for item in expanded], [1, 2, 7, None])
        self.assertEqual(expanded[-1], {"original": True})
        self.assertEqual(items, before)
        defaults = expand_instances("subset_sum", items)
        self.assertEqual([item.get("seed") for item in defaults], [0, 7, None])

    def test_relative_instance_files_for_both_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / "subset.json", {"bits": 16, "set_size": 8})
            save(root / "factor.json", {"number": "15", "p": "3", "q": "5"})
            with patch("harbor_adapter.batch.ROOT", root):
                subset = expand_instances("subset_sum", ["subset.json"], [3, 4])
                factors = expand_instances("factorization", ["factor.json"])
            self.assertEqual([item["seed"] for item in subset], [3, 4])
            self.assertEqual(factors, [{"number": 15, "p": 3, "q": 5}])

    def test_invalid_inputs_leave_no_experiment_artifacts(self):
        for overrides, error in (
            ({"instances": []}, "instances must be a nonempty list"),
            ({"seeds": []}, "seeds must be a nonempty list"),
            ({"seeds": [True]}, "seed must be an integer"),
            ({"conditions": []}, "conditions must be a nonempty list"),
            ({"conditions": ["manual-only"]}, "does not support condition"),
            ({"instances": [{"bits": 16, "set_size": 8}, 123]}, "Each instance must"),
        ):
            with (
                self.subTest(overrides=overrides),
                tempfile.TemporaryDirectory() as tmp,
            ):
                directory = Path(tmp) / "experiment"
                config = dict(
                    name="test",
                    profile="deepseek-v4-flash",
                    task="subset_sum",
                    instances=[{"bits": 16, "set_size": 8}],
                )
                config.update(overrides)
                with patch("harbor_adapter.batch.subprocess.run") as export:
                    with self.assertRaisesRegex(ValueError, error):
                        prepare(config, directory)
                    export.assert_not_called()
                self.assertFalse(directory.exists())

    def test_prepare_exports_file_instances_with_explicit_and_expanded_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "instance.json"
            save(source, {"bits": 16, "set_size": 8})
            config = dict(
                name="test",
                profile="deepseek-v4-flash",
                task="subset_sum",
                instances=[str(source), {"bits": 16, "set_size": 8, "seed": 7}],
                seeds=[1, 2],
                target_trials=1,
            )
            directory = root / "experiment"
            manifest = prepare(config, directory)
            self.assertEqual(len(manifest["trials"]), 3)
            specs = [
                read(directory / "settings" / sid / "setting.json")
                for sid in manifest["settings"]
            ]
            self.assertEqual([spec["instance"]["seed"] for spec in specs], [1, 2, 7])
            self.assertFalse((directory / "instance.json").exists())
            check_settings(directory, manifest)
