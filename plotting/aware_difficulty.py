"""Difficulty sweeps with the shared prohibited-avenues baseline prompt."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plotting.common import DATASETS, ROOT, MissingData, main, plt, tip, use_theme
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

PANELS = (
    ("factorization", "Prime factorisation · 10 Fermat increments", "Semiprime bits"),
    ("subset_sum", "Subset sum · 64 integers", "Integer bits"),
)


def load():
    path = ROOT / DATASETS["aware_difficulty"]
    if not path.exists():
        raise MissingData(f"{path} does not exist")
    return json.loads(path.read_text())["groups"]


def figure(theme_name, metric):
    theme = use_theme(theme_name)
    groups = load()
    paper = theme_name == "paper"
    fig, axes = plt.subplots(
        1, 2, figsize=(theme["width"], 3.0 if paper else 3.8), layout="constrained"
    )
    for ax, (task, title, xlabel), color in zip(axes, PANELS, theme["lines"]):
        rows = sorted(
            (r for r in groups if r["task"] == task), key=lambda r: r["bits"]
        )
        ax.plot(
            [r["bits"] for r in rows],
            [100 * r[metric] / r["n"] for r in rows],
            color=color,
            linewidth=1.6,
            zorder=3,
        )
        for row in rows:
            count, n = row[metric], row["n"]
            (point,) = ax.plot(
                row["bits"],
                100 * count / n,
                marker="o",
                markersize=5,
                color=color,
                zorder=4,
            )
            if metric == "any_observed_cheating":
                routes = row["observed_attempts"]
                detail = (
                    f"{count}/{n} flagged attempts ({100 * count / n:.0f}%); "
                    f"computation {routes['A']}, answer-key access {routes['B']}, "
                    f"tampering {routes['C']}"
                )
                if task == "subset_sum" and row["bits"] == 32:
                    detail += (
                        "; includes two boundary cases: unexecuted replay code "
                        "and index-pattern generation"
                    )
            else:
                detail = (
                    f"{count}/{n} accepted ({100 * count / n:.0f}%); "
                    "all accepted answers derived manually"
                )
            tip(fig, point, f"{title}, {row['bits']} bits: {detail}")
        ax.set_xscale("log", base=2)
        ax.xaxis.set_major_locator(FixedLocator([r["bits"] for r in rows]))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}"))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_ylim(-5, 105)
        ax.set_yticks(range(0, 101, 20), labels=[f"{y}%" for y in range(0, 101, 20)])
        ax.set_xlabel(xlabel, labelpad=6)
        ax.set_ylabel(
            "Cheating Rate" if metric == "any_observed_cheating" else "Acceptance Rate"
        )
        ax.set_title(title.replace(" · ", "\n") if paper else title, pad=12)
        ax.tick_params(length=0)
        ax.grid(axis="both", color=theme["grid"], linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    return fig


FIGURES = {
    "aware-difficulty-cheating": lambda theme: figure(theme, "any_observed_cheating"),
    "aware-difficulty-acceptance": lambda theme: figure(theme, "accepted"),
}


if __name__ == "__main__":
    main(FIGURES, __doc__)
