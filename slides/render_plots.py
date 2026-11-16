"""Render the deck's plots with its palette and larger type."""

from pathlib import Path
import sys
import re
from html import unescape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plotting.common import THEMES, plt, svg
from plotting.controlled_tools import FIGURES as CONTROLLED_FIGURES
from plotting.routes import FIGURES as ROUTE_FIGURES
from plotting import routes
from plotting.difficulty import FIGURES


def align_bar_legend(fig):
    """Use identical, centered legends across the bar-chart slides."""
    legend = fig.legends[0]
    handles = list(legend.legend_handles)
    labels = ["Accepted answer", "Attempted or accessed only"]
    legend.remove()
    fig.legend(handles, labels, loc="outside upper center", ncols=2,
               frameon=False, handlelength=1, handleheight=1,
               columnspacing=2.5)


def main():
    theme = THEMES["light"]
    theme.update(
        background="#fafbf7",
        text="#182520",
        muted="#65736b",
        grid="#e2e8df",
        axis="#c6ccc6",
        lines=["#246b56", "#c47f00"],
        font=14,
    )
    theme["rc"].update(
        {
            "font.size": 14,
            "axes.labelsize": 14,
            "axes.titlesize": 14,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "legend.fontsize": 13,
        }
    )
    for name, render in FIGURES.items():
        path = ROOT / "slides" / "assets" / "figures" / f"{name}-light.svg"
        fig = render("light")
        if name == "factorization-difficulty":
            fig.axes[0].set_title("a) Bit length sweep (at 10 search increments)")
            fig.axes[1].set_title("b) Search increment sweep (at 32 bit)")
            fig.axes[1].set_xlabel("Search increments")
        else:
            fig.axes[0].set_title("a) Bit length sweep (at 64 integers)")
            fig.axes[1].set_title("b) Set size sweep (at 32 bit)")
            fig.axes[0].set_xlabel("Integer bits")
            fig.axes[1].set_xlabel("Set size")
        # Identical canvas and axes bounds keep both slides aligned, even
        # when their tick labels and panel captions have different lengths.
        fig.set_layout_engine("none")
        fig.set_size_inches(12, 4.5)
        fig.axes[0].set_position([0.085, 0.17, 0.385, 0.60])
        fig.axes[1].set_position([0.59, 0.17, 0.385, 0.60])
        fig.legends[0].set_bbox_to_anchor((0.5, 1.0))
        fig.savefig(path, format="svg", bbox_inches=None, pad_inches=0,
                    metadata={"Date": None})
        plt.close(fig)
        print(path.relative_to(ROOT))

    report = (ROOT / "results.html").read_text()
    original = re.search(
        r'<h3 class="model-heading">With the log path</h3>.*?(<svg\b.*?</svg>)',
        report, re.S,
    ).group(1)
    theme.update(width=14.5, used="#246b56", attempted="#c6d5c7")
    fig = ROUTE_FIGURES["subset-sum-16-deepseek"]("light")
    source_tips = sorted(unescape(t) for t in re.findall(r"<title>(.*?)</title>", original, re.S))
    if sorted(fig.tips.values()) != source_tips:
        raise ValueError("With the log path: current data differ from results.html")
    plt.close(fig)
    fig = routes.figure(
        "light",
        routes.conditions("deepseek", routes.reviews("subset-sum-16"), subset=True),
        routes.LABELS["subset-sum"],
        idle=False,
    )
    align_bar_legend(fig)
    path = ROOT / "slides" / "assets" / "figures" / "with-log-path.svg"
    path.write_text(svg(fig, "light"))
    print(path.relative_to(ROOT))

    # Keep the final two report figures' data, with presentation styling.
    originals = re.findall(r"<svg\b.*?</svg>", (ROOT / "results.html").read_text(), re.S)[-2:]
    theme.update(width=14.5, used="#246b56", attempted="#c6d5c7")
    for name, original in zip(
        ("controlled-tools-methods-128", "controlled-tools-methods-128-kimi"), originals
    ):
        fig = CONTROLLED_FIGURES[name]("light")
        # Tooltip counts encode each bar's trial counts and acceptance status.
        # Verify against the requested report snapshot before replacing it.
        tips = lambda text: sorted(unescape(t) for t in re.findall(r"<title>(.*?)</title>", text, re.S))
        if sorted(fig.tips.values()) != tips(original):
            raise ValueError(f"{name}: current data differ from results.html")
        # Presentation grouping: show unknown manual-evidence fragments as
        # solid manual-work segments while retaining the source audit data.
        for ax in fig.axes:
            for patch in ax.patches:
                if patch.get_hatch():
                    patch.set_hatch(None)
                    patch.set_facecolor(theme["attempted"])
                    patch.set_edgecolor("none")
        legend = fig.legends[0]
        handles = list(legend.legend_handles)[:2]
        labels = [text.get_text() for text in legend.get_texts()][:2]
        legend.remove()
        fig.legend(handles, labels, loc="outside upper left", ncols=2,
                   frameon=False, handlelength=1, handleheight=1)
        align_bar_legend(fig)
        rendered = svg(fig, "light")
        path = ROOT / "slides" / "assets" / "figures" / f"{name}.svg"
        path.write_text(rendered)
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
