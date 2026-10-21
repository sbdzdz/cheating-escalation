"""Cheating rate against task difficulty, for prime factorization and subset sum."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

from plotting.common import (
    DATASETS,
    MODELS,
    ROOT,
    MissingData,
    main,
    plt,
    tip,
    use_theme,
)


def read(path):
    path = ROOT / path
    if not path.exists():
        raise MissingData(f"{path} does not exist")
    # Levels without finished trials carry no rate.
    return [r for r in json.loads(path.read_text())["levels"] if r["n"] > 0]


def factorization_levels(model):
    """Load the final factorization series for a model."""
    return read(DATASETS["factorization"][model])


def subset_levels(model):
    return read(DATASETS["subset_sum"][model])


def cheating_rate(level):
    """Share of trials whose submitted answer came from computation, lookup or tampering."""
    return sum(level["sources"].get(k, 0) for k in ("A", "B", "C")) / level["n"]


def panel(fig, ax, theme, datasets, key, xlabel, title, zero=False, powers=True):
    ticks = sorted({r[key] for _, levels in datasets for r in levels})
    # Zero is a separate reference position; positive values use a log scale.
    position = lambda x: 0.1 if zero and x == 0 else x
    for model, levels in datasets:
        color = theme["models"][model]
        first = model == datasets[0][0]
        rows = sorted(levels, key=lambda r: r[key])
        x = [position(r[key]) for r in rows]
        ax.plot(
            x,
            [100 * cheating_rate(r) for r in rows],
            color=color,
            linestyle="-" if first else "--",
            linewidth=1.5,
            zorder=3 if first else 2,
        )
        for r, xi in zip(rows, x):
            (point,) = ax.plot(
                [xi],
                [100 * cheating_rate(r)],
                marker="o",
                markersize=4.5,
                color=color,
                markerfacecolor=color if first else theme["background"],
                zorder=4 if first else 3,
            )
            count = sum(r["sources"].get(k, 0) for k in ("A", "B", "C"))
            tip(
                fig,
                point,
                f"{MODELS[model]}, {r[key]:,}: {count}/{r['n']} trials ({100 * cheating_rate(r):.0f}%)",
            )
    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator([position(t) for t in ticks]))
    labels = {
        position(t): (
            rf"$10^{{{len(str(t)) - 1}}}$" if powers and t >= 1000 else f"{t:,}"
        )
        for t in ticks
    }
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: labels.get(x, "")))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_ylim(-5, 105)
    ax.set_yticks([0, 25, 50, 75, 100], labels=["0%", "25%", "50%", "75%", "100%"])
    ax.tick_params(axis="y", colors=theme["muted"])
    ax.set_xlabel(xlabel, labelpad=6)
    ax.set_ylabel("Cheating rate", labelpad=6)
    ax.set_title(title, pad=9)
    ax.grid(axis="y", color=theme["grid"], linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    if zero:
        ax.text(
            0.32,
            -0.04,
            "//",
            transform=ax.get_xaxis_transform(),
            ha="center",
            color=theme["muted"],
        )


def figure(theme_name, load, panels):
    theme = use_theme(theme_name)
    data = []
    for model in MODELS:
        try:
            data.append((model, load(model)))
        except MissingData:
            if model == "deepseek":
                raise
    paper = theme_name == "paper"
    if paper:
        fig, axes = plt.subplots(1, 2, figsize=(5.5, 3.0))
        fig.subplots_adjust(left=0.125, right=0.995, bottom=0.22, top=0.77, wspace=0.45)
    else:
        fig, axes = plt.subplots(
            1, 2, figsize=(theme["width"], 4.2), layout="constrained"
        )
        fig.get_layout_engine().set(wspace=0.08)
    for ax, (key, label, title, select, zero) in zip(axes, panels):
        # Powers of ten need the paper's math font; the report spells numbers out.
        panel(
            fig,
            ax,
            theme,
            [(m, [r for r in levels if select(r)]) for m, levels in data],
            key,
            label,
            title,
            zero,
            powers=paper,
        )
    handles = [
        Line2D(
            [],
            [],
            color=theme["models"][m],
            linestyle="-" if i == 0 else "--",
            marker="o",
            markersize=4.5,
            markerfacecolor=theme["models"][m] if i == 0 else theme["background"],
            label=MODELS[m],
        )
        for i, (m, _) in enumerate(data)
    ]
    fig.legend(
        handles=handles,
        loc="upper center" if paper else "outside upper center",
        ncol=2,
        frameon=False,
        handlelength=1.7,
        columnspacing=1.2,
    )
    if not paper:
        return fig
    # Align the outer edge of the left ylabel with the page's text margin.
    fig.canvas.draw()
    label_left = axes[0].yaxis.label.get_window_extent(fig.canvas.get_renderer()).x0
    shift = label_left / fig.bbox.width
    box = axes[0].get_position()
    axes[0].set_position([box.x0 - shift, box.y0, box.width + shift, box.height])
    return fig


FIGURES = {
    "factorization-difficulty": lambda theme: figure(
        theme,
        factorization_levels,
        [
            (
                "bits",
                "Semiprime bits",
                "(a) 10 Fermat increments",
                lambda r: r["bits"] >= 8 and r["fermat_increments"] == 10,
                False,
            ),
            (
                "fermat_increments",
                "Fermat increments",
                "(b) 32-bit semiprimes",
                lambda r: r["bits"] == 32,
                True,
            ),
        ],
    ),
    "subset-sum-difficulty": lambda theme: figure(
        theme,
        subset_levels,
        [
            (
                "bits",
                "Integer bits",
                "(a) 64 integers",
                lambda r: r["set_size"] == 64,
                False,
            ),
            (
                "set_size",
                "Set size",
                "(b) 32-bit integers",
                lambda r: r["bits"] == 32,
                False,
            ),
        ],
    ),
}


if __name__ == "__main__":
    main(FIGURES, __doc__)
