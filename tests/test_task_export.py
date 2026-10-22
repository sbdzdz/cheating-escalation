import subprocess
import tempfile
import unittest
from pathlib import Path

from environment.batch import files_hash
from environment.export import export, export_tasks
from environment.tasks import get_task


class TaskExportTests(unittest.TestCase):
    def test_export_api_preserves_task_files(self):
        for kind, instance in (
            ("factorization", {"number": "15", "p": "3", "q": "5"}),
            ("subset_sum", {"bits": 16, "set_size": 8, "seed": 7}),
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / "source"
                (row,) = get_task(kind).build(source, [4], instance)
                expected = export(
                    row, root / "expected", "b-caught", source=source, task_kind=kind
                )
                (actual,) = export_tasks(
                    kind, root / "actual", instance=instance, condition="b-caught"
                )
                before = files_hash(expected.rglob("*"), expected)
                after = files_hash(actual.rglob("*"), actual)
                # Rebuilding Git's index changes its filesystem stat cache. Compare
                # staged paths, modes and object IDs, while all other bytes must match.
                for name in list(before):
                    if name.endswith("/.git/index"):

                        def staged(root):
                            return subprocess.check_output(
                                [
                                    "git",
                                    "--git-dir",
                                    str((root / name).parent),
                                    "ls-files",
                                    "--stage",
                                ]
                            )

                        self.assertEqual(staged(expected), staged(actual))
                        del before[name]
                        del after[name]
                self.assertEqual(before, after)

    def test_prompt_matches_configured_timeout_for_both_tasks(self):
        for kind in ("factorization", "subset_sum"):
            for timeout, duration in (
                (3600, "60 minutes"),
                (60, "1 minute"),
                (61, "61 seconds"),
                (1, "1 second"),
            ):
                with (
                    self.subTest(kind=kind, timeout=timeout),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    (task,) = export_tasks(kind, Path(tmp), agent_timeout_sec=timeout)
                    prompt = (task / "instruction.md").read_text()
                    self.assertIn(f"{duration} on the clock", prompt)
                    self.assertIn(
                        f"timeout_sec = {timeout}", (task / "task.toml").read_text()
                    )
                    rendered = list(
                        (task / "environment/rootfs").rglob("*.rendered.md")
                    )
                    self.assertTrue(
                        any(p.read_text().rstrip() == prompt.rstrip() for p in rendered)
                    )
                    if timeout != 3600:
                        self.assertNotIn("60 minutes on the clock", prompt)

    def test_invalid_timeout_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            with self.assertRaisesRegex(ValueError, "positive integer"):
                export_tasks("subset_sum", output, agent_timeout_sec=0)
            self.assertFalse(output.exists())
