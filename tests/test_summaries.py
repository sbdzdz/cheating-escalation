import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harbor_adapter.summaries import summarize, write_summary

CLASSIFICATION = dict(source="A", A=1, B=0, C=0, manual_evidence="none")


class SummaryTests(unittest.TestCase):
    def row(self, run, **dimensions):
        return dict(
            run_ids=[run], classification=CLASSIFICATION, cost_usd="0.10", **dimensions
        )

    def test_factorization_accepts_distinct_numbers_at_same_difficulty(self):
        rows = [
            self.row("a", number="15", bits=4, fermat_increments=0),
            self.row("b", number="21", bits=4, fermat_increments=0),
        ]
        result = summarize(
            rows, task="factorization", model="test", condition="baseline"
        )
        self.assertEqual(result["total_cost_usd"], "0.20")
        self.assertEqual(result["levels"][0]["numbers"], ["15", "21"])
        self.assertEqual(result["levels"][0]["sources"], {"A": 2})
        single = summarize(
            rows[:1], task="factorization", model="test", condition="baseline"
        )
        self.assertEqual(single["levels"][0]["number"], "15")

    def test_duplicate_runs_rejected(self):
        row = self.row("same", number="15", bits=4, fermat_increments=0)
        with self.assertRaisesRegex(ValueError, "Duplicate runs"):
            summarize(
                [row, row], task="factorization", model="test", condition="baseline"
            )

    def test_subset_sum_cli_aggregates_seeds_and_separates_solution_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trials = []
            for i, (seed, solution_size) in enumerate([(1, 2), (2, 2), (3, 3)]):
                setting = root / "settings" / str(i)
                setting.mkdir(parents=True)
                (setting / "setting.json").write_text(
                    json.dumps(
                        dict(
                            task="subset_sum",
                            profile={"model": "test-model"},
                            condition="baseline",
                            instance=dict(
                                bits=8,
                                set_size=4,
                                seed=seed,
                                solution_size=solution_size,
                            ),
                        )
                    )
                )
                folder = root / str(i) / "trials" / "trial"
                folder.mkdir(parents=True)
                for name, content in [
                    ("transcript", {}),
                    ("classification", CLASSIFICATION),
                    ("verifier", {}),
                ]:
                    (folder / f"{name}.json").write_text(json.dumps(content))
                trials.append(
                    dict(
                        id=str(i),
                        run_id=str(i),
                        setting=str(i),
                        status="finished",
                        output=str(root / str(i)),
                        cost_usd="0.10",
                    )
                )
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"trials": trials}))
            output = root / "report.json"
            script = (
                Path(__file__).resolve().parents[1] / "scripts/summarize_trials.py"
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    f"manifest={manifest}",
                    f"output={output}",
                ],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["task"], "subset_sum")
            self.assertEqual(report["model"], "test-model")
            self.assertEqual([r["n"] for r in report["levels"]], [2, 1])
            self.assertEqual(report["total_cost_usd"], "0.30")
            self.assertFalse((root / ".hydra").exists())

    def test_historical_retries_and_unfinished_trials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            output = root / "report.json"
            row = self.row("new", number="15", bits=4, fermat_increments=0)
            data = dict(
                settings={"s": dict(model="historical-model", condition="baseline")},
                trials=[
                    dict(id="old", status="error"),
                    dict(
                        id="new",
                        status="finished",
                        retry_of="old",
                        setting="s",
                        historical_row=row,
                    ),
                ],
            )
            manifest.write_text(json.dumps(data))
            config = dict(manifest=str(manifest), output=str(output))
            report = write_summary(config)
            self.assertEqual(report["n"], 1)
            self.assertEqual(report["model"], "historical-model")
            self.assertEqual(report["excluded_retry_attempts"][0]["id"], "old")
            output.unlink()
            data["trials"][1]["status"] = "pending"
            manifest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unfinished"):
                write_summary(config)
            self.assertFalse(output.exists())
