import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from harbor_adapter.experiment_config import load_config
from plotting.common import MissingData, plt, run_plots

ROOT = Path(__file__).resolve().parents[1]


class PlotConfigTests(unittest.TestCase):
    def test_yaml_defaults_follow_format_and_theme(self):
        for overrides, theme, output in [
            ([], "paper", "paper/fig"),
            (["format=svg"], "dark", "reports/figures"),
            (["theme=light"], "light", "reports/figures"),
        ]:
            config = load_config("plot", overrides)
            self.assertEqual(config["theme"], theme)
            self.assertEqual(config["output"], output)
        self.assertEqual(load_config("plot", ["output=custom"])["output"], "custom")

    def test_selection_validation_and_rendering(self):
        def figure(theme):
            fig, ax = plt.subplots()
            ax.plot([1, 2], [3, 4])
            return fig

        with tempfile.TemporaryDirectory() as tmp:
            unwanted = Mock(side_effect=AssertionError("unselected figure rendered"))
            figures = {"selected": figure, "other": unwanted}
            config = load_config(
                "plot", [f"output={tmp}", "names=[selected]", "format=svg"]
            )
            paths = run_plots(figures, config)
            self.assertEqual(paths, [Path(tmp) / "selected.svg"])
            self.assertIn("<svg", paths[0].read_text())
            unwanted.assert_not_called()
            for field, value in [
                ("names", ["unknown"]),
                ("theme", "unknown"),
                ("format", "png"),
            ]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    run_plots(figures, dict(config, **{field: value}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    run_plots(
                        {"selected": Mock(side_effect=MissingData("missing"))}, config
                    ),
                    [],
                )

    def test_cli_lists_and_resolves_config_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = ROOT / "plotting/routes.py"
            for overrides, expected in [
                (["list=true"], "subset-sum-16-bshown-deepseek"),
                (["format=svg", "--cfg", "job", "--resolve"], "theme: dark"),
            ]:
                result = subprocess.run(
                    [sys.executable, str(script), *overrides],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                self.assertEqual(list(Path(tmp).iterdir()), [])
