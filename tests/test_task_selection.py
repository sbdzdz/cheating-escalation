import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harbor_adapter.tasks import get_task, resolve_task
from scripts.export_harbor import export

ROOT = Path(__file__).resolve().parents[1]


class TaskSelectionTests(unittest.TestCase):
    def test_run_selection_matches_export_for_both_tasks(self):
        cases = [
            ("factorization", 4, None),
            ("factorization", 5, {"number": "15", "p": "3", "q": "5"}),
            ("subset_sum", 4, {"original": True}),
            ("subset_sum", 5, None),
            ("subset_sum", 4, {"bits": 16, "set_size": 8, "seed": 7}),
        ]
        for kind, question, instance in cases:
            with self.subTest(kind=kind, question=question, instance=instance):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    source = root / "source"
                    task = get_task(kind)
                    (row,) = task.build(source, [question], instance)
                    for condition in ("baseline", "b-caught"):
                        exported = export(
                            row,
                            root / "export",
                            condition,
                            source=source,
                            task_kind=kind,
                        )
                        selected = resolve_task(
                            kind,
                            question=question,
                            instance=instance,
                            condition=condition,
                            output=root / "export",
                        )
                        self.assertEqual(selected, exported)
                        self.assertTrue((selected / "task.toml").is_file())
                    if instance is not None:
                        path = root / "instance.json"
                        path.write_text(json.dumps(instance))
                        self.assertEqual(
                            resolve_task(kind, question=question, instance=path),
                            resolve_task(kind, question=question, instance=instance),
                        )

    def test_explicit_snapshot_needs_no_instance_file(self):
        self.assertEqual(
            resolve_task(
                "subset_sum", task_path="snapshot/task", instance="missing.json"
            ),
            Path("snapshot/task"),
        )

    def test_task_constraints_fail_before_building(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source"
            task = get_task("subset_sum")
            with self.assertRaisesRegex(ValueError, "question 4"):
                task.build(output, [5], {"bits": 16, "set_size": 8, "seed": 7})
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError, "does not support condition"):
                task.name(condition="manual-only")
            with self.assertRaisesRegex(ValueError, "Unknown task"):
                get_task("typo")

    def test_subset_export_cli_and_trial_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            instance = root / "instance.json"
            instance.write_text('{"bits":16,"set_size":8,"seed":7}')
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/export_harbor.py"),
                    "--task",
                    "subset_sum",
                    "--instance",
                    str(instance),
                    "--output",
                    str(root / "exports"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            selected = resolve_task(
                "subset_sum", instance=instance, output=root / "exports"
            )
            self.assertEqual(Path(result.stdout.strip()), selected.resolve())
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_trial.py"),
                    "--task",
                    "subset_sum",
                    "--task-path",
                    str(selected),
                    "--agent",
                    "nop",
                    "--print-config",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            config = json.loads(result.stdout)
            self.assertEqual(config["agents"][0]["name"], "nop")
