"""Observed manual work and shortcut calls in the controlled-tool conditions."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.patches import Patch

from plotting import routes
from plotting.common import DATASETS, ROOT, MissingData, main, tip, use_theme

CONDITIONS = (
    ("aware-baseline", "Baseline"),
    ("aware-a-caught", "Computation penalised"),
    ("aware-b-caught", "Answer lookup penalised"),
    ("aware-ab-caught", "Both penalised"),
)


def figure(
    theme_name,
    summary_key="controlled_tools_summary",
    manual_key="controlled_tools_manual",
    include_unestablished_manual=False,
):
    paths = [ROOT / DATASETS[key] for key in (summary_key, manual_key)]
    for path in paths:
        if not path.exists():
            raise MissingData(f"{path} does not exist")
    data, review = (json.loads(path.read_text()) for path in paths)
    manual = {r["trial_id"]: r for r in review["trials"]}
    unknown_label = review.get("unknown_label", "Manual evidence unavailable")
    if set(manual) != {r["trial_id"] for r in data["trials"]}:
        raise ValueError("Manual evidence does not cover the plotted controlled trials")
    panels, unknown = [], []
    for condition, title in CONDITIONS:
        rows = [r for r in data["trials"] if r["condition"] == condition]
        if not rows:
            raise MissingData(f"No controlled trials for {condition}")
        used = [0, 0, 0]
        attempted = [0, 0, 0]
        absent = 0
        for row in rows:
            observed = manual[row["trial_id"]]["manual_attempt"]
            if include_unestablished_manual and observed is None:
                observed = True
            absent += observed is None
            accepted_manual = row["accepted"] and not row["answer_returned"]
            used[0] += accepted_manual and observed is True
            attempted[0] += observed is True and not accepted_manual
            for i, key in enumerate(("computation_attempt", "lookup_attempt"), 1):
                accepted_key = key.removesuffix("_attempt") + "_accepted_after_access"
                produced = row.get(
                    accepted_key, row[key] and row["accepted_after_exposure"]
                )
                used[i] += produced
                attempted[i] += row[key] and not produced
        panels.append(
            (title, dict(n=len(rows), used=used, attempted=attempted, idle=0))
        )
        unknown.append(absent)
    fig = routes.figure(
        theme_name,
        panels,
        ["Manual solving", "Computation", "Answer lookup"],
        idle=False,
        columns=4,
        status_labels=(
            "Accepted after access / manual answer",
            "Attempted or accessed without acceptance",
        ),
    )
    theme = use_theme(theme_name)
    for ax, (title, counts), count in zip(fig.axes, panels, unknown):
        if count:
            (bar,) = ax.barh(
                0,
                count / counts["n"],
                left=(counts["used"][0] + counts["attempted"][0]) / counts["n"],
                height=0.53,
                facecolor=theme["background"],
                edgecolor=theme["muted"],
                hatch="///",
                linewidth=0.7,
            )
            tip(
                fig,
                bar,
                f"{title}: {unknown_label.lower()} for {count}/{counts['n']} trials. These are not confirmed manual attempts.",
            )
    if any(unknown):
        legend = fig.legends[0]
        handles = list(legend.legend_handles) + [
            Patch(facecolor=theme["background"], edgecolor=theme["muted"], hatch="///")
        ]
        labels = [t.get_text() for t in legend.get_texts()] + [unknown_label]
        legend.remove()
        fig.legend(
            handles=handles,
            labels=labels,
            loc="outside upper left",
            ncols=3,
            frameon=False,
            handlelength=1,
            handleheight=1,
        )
    return fig


def shortcut_figure(theme_name, summary_key):
    """Plot audited helper operations without imputing unreviewed manual work."""
    path = ROOT / DATASETS[summary_key]
    if not path.exists():
        raise MissingData(f"{path} does not exist")
    data = json.loads(path.read_text())
    panels = []
    for condition, title in CONDITIONS:
        rows = [r for r in data["trials"] if r["condition"] == condition]
        if not rows:
            raise MissingData(f"No completed controlled trials for {condition}")
        used, attempted = [], []
        for key in ("computation_attempt", "lookup_attempt"):
            accepted_key = key.removesuffix("_attempt") + "_accepted_after_access"
            accepted = sum(r[accepted_key] for r in rows)
            used.append(accepted)
            attempted.append(sum(r[key] for r in rows) - accepted)
        panels.append(
            (title, dict(n=len(rows), used=used, attempted=attempted, idle=0))
        )
    fig = routes.figure(
        theme_name,
        panels,
        ["Computation", "Answer lookup"],
        idle=False,
        columns=4,
        status_labels=(
            "Accepted after access",
            "Attempted or accessed without acceptance",
        ),
    )
    theme = use_theme(theme_name)
    for ax in fig.axes:
        for text in ax.get_yticklabels():
            text.set_color(theme["flagged"])
    return fig


FIGURES = {
    "controlled-tools-methods": figure,
    "controlled-tools-methods-128": lambda theme: figure(
        theme,
        "controlled_tools_128_summary",
        "controlled_tools_128_manual",
        include_unestablished_manual=True,
    ),
    "controlled-tools-methods-128-kimi": lambda theme: figure(
        theme,
        "controlled_tools_128_kimi_summary",
        "controlled_tools_128_kimi_manual",
        include_unestablished_manual=True,
    ),
    "controlled-factorization-512-deepseek": lambda theme: figure(
        theme,
        "controlled_factorization_512_deepseek",
        "controlled_factorization_512_deepseek_manual",
        include_unestablished_manual=True,
    ),
    "controlled-factorization-512-kimi": lambda theme: figure(
        theme,
        "controlled_factorization_512_kimi",
        "controlled_factorization_512_kimi_manual",
        include_unestablished_manual=True,
    ),
}


if __name__ == "__main__":
    main(FIGURES, __doc__)
