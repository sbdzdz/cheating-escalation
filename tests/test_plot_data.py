import json
import tempfile
import unittest
from pathlib import Path

from harbor_adapter.experiment_config import load_config
from plotting import difficulty, routes
from plotting.common import DATASETS, MissingData, plt, run_plots


class PlotDataTests(unittest.TestCase):
    def test_configured_inputs_and_replacements_are_scoped_to_render(self):
        original = dict(DATASETS)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, levels in [
                ("base", [dict(bits=32, n=2), dict(bits=128, n=3)]),
                ("extra", [dict(bits=128, n=5)]),
                ("subset", [dict(bits=8, n=4), dict(bits=16, n=0)]),
            ]:
                (root / f"{name}.json").write_text(json.dumps({"levels": levels}))
            (root / "review.json").write_text(
                json.dumps({"trials": [{"run_id": "custom"}]})
            )
            cfg = load_config(
                "plot",
                [
                    f"output={root}/figures",
                    f"data.reviews.factorization=[{root}/review.json]",
                    f"data.factorization.deepseek.base={root}/base.json",
                    f"data.factorization.deepseek.replacements=[{{bits:128,path:{root}/extra.json}},{{bits:256,path:{root}/missing.json}}]",
                    f"data.subset_sum.deepseek={root}/subset.json",
                ],
            )

            def figure(theme):
                self.assertEqual(
                    routes.reviews("factorization"), [{"run_id": "custom"}]
                )
                self.assertEqual(
                    difficulty.factorization_levels("deepseek"),
                    [dict(bits=32, n=2), dict(bits=128, n=5)],
                )
                self.assertEqual(
                    difficulty.subset_levels("deepseek"), [dict(bits=8, n=4)]
                )
                return plt.figure()

            run_plots({"example": figure}, cfg)
            self.assertEqual(DATASETS, original)
            (root / "extra.json").write_text(
                json.dumps({"levels": [dict(bits=64, n=5)]})
            )
            with self.assertRaisesRegex(ValueError, "unexpected bit lengths"):
                run_plots({"example": figure}, cfg)
            self.assertEqual(DATASETS, original)

    def test_missing_absolute_input_reports_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(MissingData, "absent.json"):
                difficulty.read(str(Path(tmp) / "absent.json"))
