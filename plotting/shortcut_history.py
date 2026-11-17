"""Per-task audited shortcut categories by the retained outcome of R1 or R2."""

import json

from plotting.common import DATASETS, ROOT, MissingData, main, plt, tip, use_theme

OUTCOMES = [
    ("ineffective", "Ineffective"),
    ("effective-not-caught", "Effective, not caught"),
    ("effective-caught", "Effective, caught"),
]


def figure(theme_name, task):
    path = ROOT / DATASETS["shortcut_history"]
    if not path.exists():
        raise MissingData(str(path))
    data = json.loads(path.read_text())
    theme = use_theme(theme_name)
    fig, axes = plt.subplots(
        1, 2, figsize=(theme["width"], 4.7), sharey=True, layout="constrained"
    )
    fig.get_layout_engine().set(rect=(0, 0, 1, 0.88))
    categories = [
        ("None", lambda r: not r["computation_attempt"] and not r["lookup_attempt"]),
        ("R1", lambda r: r["computation_attempt"]),
        ("R2", lambda r: r["lookup_attempt"]),
    ]
    for ax, operation in zip(axes, ["r1", "r2"]):
        ticks, ticklabels = [], []
        for group_index, (outcome, title) in enumerate(OUTCOMES):
            rows = [
                r
                for r in data["trials"]
                if r["task"] == task and r["condition"] == f"{operation}-{outcome}"
            ]
            n = len(rows)
            if not n:
                raise MissingData(
                    f"No finished trials for {task}: {operation}-{outcome}"
                )
            for i, (label, matches) in enumerate(categories):
                selected = [r for r in rows if matches(r)]
                bottom = 0
                for accepted, color, status in [
                    (True, theme["used"], "Accepted answer"),
                    (False, theme["attempted"], "No accepted answer"),
                ]:
                    count = sum(r["accepted"] == accepted for r in selected)
                    bar = ax.bar(
                        group_index * 4 + i,
                        count / n,
                        bottom=bottom,
                        width=0.53,
                        color=color,
                        label=status if i == 0 and group_index == 0 else None,
                    )[0]
                    tip(
                        fig,
                        bar,
                        f"Previous {operation.upper()}: {title}. {label.replace(chr(10), ' ')} — {status}: {count}/{n} runs ({count / n:.0%})."
                        + (
                            " None means no prohibited operation recorded."
                            if i == 0
                            else " R1/R2 count recorded attempts and may overlap; acceptance does not establish the answer source."
                        ),
                    )
                    bottom += count / n
            ticks.extend(group_index * 4 + i for i in range(3))
            ticklabels.extend(["None", "R1", "R2"])
            ax.text(
                group_index * 4 + 1,
                -0.12,
                title,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                color=theme["muted"],
            )
        ax.set_title(f"Previous {operation.upper()} outcome", fontweight="bold", pad=16)
        ax.set_xticks(ticks, ticklabels)
        for i, label in enumerate(ax.get_xticklabels()):
            label.set_color(theme["text"] if i % 3 == 0 else theme["flagged"])
        ax.set_ylim(0, 1)
        ax.set_yticks([i / 5 for i in range(6)], [f"{i * 20}%" for i in range(6)])
        ax.set_axisbelow(True)
        ax.grid(axis="y", color=theme["grid"], linewidth=0.8)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.supylabel("Percentage of runs", color=theme["muted"], fontsize=theme["font"])
    handles, labels = axes[0].get_legend_handles_labels()
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
    "history-factorization": lambda theme: figure(theme, "factorization"),
    "history-subset-sum": lambda theme: figure(theme, "subset_sum"),
}
if __name__ == "__main__":
    main(FIGURES, __doc__)
