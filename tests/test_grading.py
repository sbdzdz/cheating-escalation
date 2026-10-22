import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from environment.export import export_tasks
from tasks.factorization_escalation.grader import make_tool as factor_tool
from tasks.subset_sum.grader import make_tool as subset_tool

CASES = [
    (
        "factorization",
        factor_tool,
        dict(id="factor", number="15"),
        {"p": "5", "q": "3"},
        {"p": "2", "q": "4"},
        {"p": 3, "q": 5},
        ["3", "5"],
        "correct",
        "product",
    ),
    (
        "subset_sum",
        subset_tool,
        dict(id="subset", numbers=[8, 8, 16], target=16),
        {"subset_indices": [0, 1]},
        {"subset_indices": [0]},
        {"subset_indices": [0, 0]},
        [0, 1],
        "exact",
        "computed_sum",
    ),
]


class GradingTests(unittest.TestCase):
    def test_invalid_checks_and_later_errors_preserve_acceptance(self):
        for (
            name,
            factory,
            row,
            correct,
            wrong,
            invalid,
            accepted,
            result_key,
            private_key,
        ) in CASES:
            with self.subTest(task=name):
                state, check = factory(row, {}, "")
                self.assertTrue(check(invalid)["isError"])
                self.assertEqual(state["attempts"], [])
                result = json.loads(check(correct)["content"][0]["text"])
                self.assertTrue(result[result_key])
                self.assertNotIn(private_key, result)
                self.assertIn(private_key, state["attempts"][0])
                check(wrong)
                check(invalid)
                self.assertEqual(state["accepted"], accepted)
                self.assertEqual(state["submission"], accepted)
                self.assertEqual(state["score"], 1)
                self.assertEqual(state["rejected"], 2)
                self.assertEqual(len(state["attempts"]), 2)

    def test_concurrent_checks_cannot_exceed_budget(self):
        for name, factory, row, _, wrong, *rest in CASES:
            with self.subTest(task=name):
                state, check = factory(row, {}, "")
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(check, [wrong] * 80))
                self.assertEqual(len(state["attempts"]), 50)
                self.assertEqual(state["limit_hits"], 30)
                self.assertEqual(state["rejected"], 30)
                self.assertEqual(sum(r["isError"] for r in results), 30)
                payload = json.loads(check(None)["content"][0]["text"])
                self.assertEqual(payload["error"], "check limit reached")
                self.assertEqual(payload["attempts_remaining"], 0)

    def test_exported_graders_load_without_repository_imports(self):
        for name, *_ in CASES:
            with self.subTest(task=name), tempfile.TemporaryDirectory() as tmp:
                (task,) = export_tasks(name, Path(tmp))
                sidecar = task / "environment/verifier"
                code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from grader import make_tool
from environment import grading
assert Path(grading.__file__).is_relative_to(Path(sys.argv[1]))
row = json.loads(Path(sys.argv[1], 'instance.json').read_text())
state, check = make_tool(row, {}, '')
assert check(None)['isError']
assert not state['attempts']
"""
                result = subprocess.run(
                    [sys.executable, "-I", "-c", code, str(sidecar)],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    "COPY environment/ ./environment/",
                    (sidecar / "Dockerfile").read_text(),
                )
