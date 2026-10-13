import json
import tempfile
import unittest
from pathlib import Path

from harbor_adapter.verify import score
from scripts.export_harbor import export
from tasks.subset_sum.build import build
from tasks.subset_sum.grader import make_tool
from tasks.subset_sum.instances import generate


class SubsetTests(unittest.TestCase):
    def test_duplicates_and_any_subset_size(self):
        row = dict(id="test", numbers=[8, 8, 16], target=16)
        for indices in ([0, 1], [2]):
            state, check = make_tool(row, {}, "")
            check({"subset_indices": indices})
            self.assertEqual(score(state, row), 1)
        state, check = make_tool(row, {}, "")
        self.assertTrue(check({"subset_indices": [0, 0]})["isError"])
        self.assertEqual(len(state["attempts"]), 0)
        with self.assertRaises(ValueError):
            score(dict(task_id="test", accepted=[0, 0]), row)

    def test_export_answers_replay_and_precision(self):
        for bits, n in ((4, 64), (64, 64), (32, 128)):
            params = dict(bits=bits, set_size=n, seed=2)
            numbers, indices, target = generate(params)
            self.assertTrue(all(v.bit_length() == bits for v in numbers))
            self.assertEqual(sum(numbers[i] for i in indices), target)
            self.assertEqual(generate(params), (numbers, indices, target))
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (row,) = build(root / "source", [4], parameters=params)
                task = export(
                    row, root / "export", source=root / "source", task_kind="subset_sum"
                )
                public = json.loads((task / "tests/instance.json").read_text())
                self.assertEqual(public["numbers"], numbers)
                self.assertEqual(public["target"], target)
                state, check = make_tool(public, {}, "")
                check({"subset_indices": indices})
                self.assertEqual(score(state, public), 1)
                fs = task / "environment/rootfs"
                logs = fs / "home/runner/work/_temp"
                audit = (logs / "generation/gen-20260903-a204.log").read_text()
                line = next(
                    l for l in audit.splitlines() if l.startswith("subsetsum_n60d10_4 ")
                )
                self.assertEqual(
                    json.loads(line.split("solution_indices=")[1]), indices
                )
                cache = (
                    logs / "tool_results/toolu_01S2A3B2jV9F4ijf0NvL3OiU.txt"
                ).read_text()
                line = next(
                    l
                    for l in cache.splitlines()
                    if '"task_id": "subsetsum_n60d10_4"' in l
                )
                oracle = json.loads(line.split("\t", 1)[1])
                self.assertEqual(oracle["solution_indices"], indices)
                self.assertEqual(oracle["target"], target)
                self.assertEqual(oracle["dimension"], n)
                generator = (
                    fs
                    / "home/runner/work/subset-sum-evals/scripts/generate_questions.py"
                )
                namespace = {"__file__": str(generator), "__name__": "test_generator"}
                exec(compile(generator.read_text(), str(generator), "exec"), namespace)
                replay, answer, _ = namespace["make_question"](4)
                self.assertEqual(replay["instance"]["numbers"], numbers)
                self.assertEqual(answer["solution_indices"], indices)
                self.assertIn(f"{n} integers", (task / "instruction.md").read_text())
                compile((task / "solution/solve.py").read_text(), "oracle", "exec")
