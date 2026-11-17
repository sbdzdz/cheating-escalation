"""Opaque shortcut attempts by retained outcome, from verifier audits."""

import json

from plotting.common import DATASETS, ROOT, MissingData, main, plt, tip, use_theme
from plotting.shortcut_history import OUTCOMES

CONDITIONS = [("baseline", "Baseline"), *OUTCOMES]


def figure(theme_name, task):
    path = ROOT / DATASETS["opaque_shortcuts"]
    if not path.exists():
        raise MissingData(str(path))
    trials = json.loads(path.read_text())["trials"]
    theme = use_theme(theme_name)
    fig, ax = plt.subplots(figsize=(theme["width"], 4.7), layout="constrained")
    fig.get_layout_engine().set(rect=(0, 0, 1, 0.88))
    categories = ["None", "R1", "R2", "R3"]
    ticks, ticklabels = [], []
    for group_index, (outcome, title) in enumerate(CONDITIONS):
        rows = [r for r in trials if r["task"] == task and r["condition"] == outcome]
        if not rows:
            raise MissingData(f"No opaque trials for {task}: {outcome}")
        n = len(rows)
        for i, label in enumerate(categories):
            bottom = 0
            for accepted, color, status in [
                (True, theme["used"], "Accepted answer"),
                (False, theme["attempted"], "No accepted answer"),
            ]:
                count = sum(
                    (r["none"] if label == "None" else label in r["operations"])
                    and r["accepted"] == accepted
                    for r in rows
                )
                bar = ax.bar(
                    group_index * 5 + i,
                    count / n,
                    bottom=bottom,
                    width=0.53,
                    color=color,
                    label=status if i == 0 and group_index == 0 else None,
                )[0]
                tip(
                    fig,
                    bar,
                    f"{title}. {label} — {status}: {count}/{n} runs ({count / n:.0%}). "
                    "R1: tool named in the treatment records; baseline has no record. R2/R3: the alternatives. "
                    "Tool attempts may overlap; acceptance does not establish the answer source.",
                )
                bottom += count / n
        ticks.extend(group_index * 5 + i for i in range(4))
        ticklabels.extend(categories)
        ax.text(
            group_index * 5 + 1.5,
            -0.12,
            title,
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            color=theme["muted"],
        )
    ax.set_title("Previous R1 outcome", fontweight="bold", pad=16)
    ax.set_xticks(ticks, ticklabels)
    for i, label in enumerate(ax.get_xticklabels()):
        label.set_color(theme["text"] if i % 4 == 0 else theme["flagged"])
    ax.set_ylim(0, 1)
    ax.set_yticks([i / 5 for i in range(6)], [f"{i * 20}%" for i in range(6)])
    ax.set_axisbelow(True)
    ax.grid(axis="y", color=theme["grid"], linewidth=0.8)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.supylabel("Percentage of runs", color=theme["muted"], fontsize=theme["font"])
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1),
        borderaxespad=0.5,
        ncols=2,
        frameon=False,
        handlelength=1,
        handleheight=1,
    )
    return fig


FIGURES = {
    "opaque-factorization": lambda theme: figure(theme, "factorization"),
    "opaque-subset-sum": lambda theme: figure(theme, "subset_sum"),
}

if __name__ == "__main__":
    main(FIGURES, __doc__)
