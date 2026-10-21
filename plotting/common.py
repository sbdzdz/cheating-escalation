"""Themes, output formats and the command line shared by the plotting scripts."""

import html
import io
import itertools
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/cheating-escalation-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

FORMATS = ("pdf", "svg")
# Keep direct figure rendering and the CLI on the same YAML defaults.
from harbor_adapter.experiment_config import load_config

THEMES = load_config("plot_styles")
DATASETS = load_config("plot_data")


MODELS = {"deepseek": "DeepSeek V4 Flash", "glm": "GLM 5.3 Flash"}


class MissingData(Exception):
    """The reviews or analyses a figure needs have not been produced yet."""


def use_theme(name):
    theme = THEMES[name]
    matplotlib.rcdefaults()
    matplotlib.rcParams.update(theme["rc"])
    matplotlib.rcParams.update(
        {
            "figure.facecolor": theme["background"],
            "axes.facecolor": theme["background"],
            "savefig.facecolor": theme["background"],
            "text.color": theme["text"],
            "axes.labelcolor": theme["muted"],
            "xtick.color": theme["muted"],
            "ytick.color": theme["text"],
            "axes.edgecolor": theme["axis"],
            # Stable ids and no timestamps, so re-rendering unchanged data changes nothing.
            "svg.hashsalt": "cheating-escalation",
        }
    )
    return theme


_tip_ids = itertools.count()


def tip(fig, artist, text):
    """Hover text in the SVG output; PDFs ignore it."""
    gid = f"tip{next(_tip_ids)}"
    artist.set_gid(gid)
    fig.tips = {**getattr(fig, "tips", {}), gid: text}


def svg(fig, theme):
    """The figure as an inline <svg> element, with hover titles."""
    buffer = io.StringIO()
    fig.savefig(
        buffer,
        format="svg",
        metadata={"Date": None},
        bbox_inches="tight",
        pad_inches=THEMES[theme]["pad"],
    )
    plt.close(fig)
    text = buffer.getvalue()
    text = text[text.index("<svg") :]
    text = re.sub(r"\s*<metadata>.*?</metadata>", "", text, count=1, flags=re.S)
    for gid, tooltip in getattr(fig, "tips", {}).items():
        text = text.replace(
            f'<g id="{gid}">', f'<g id="{gid}"><title>{html.escape(tooltip)}</title>', 1
        )
    return text


def save(fig, path, theme):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".svg":
        path.write_text(svg(fig, theme))
    else:
        fig.savefig(
            path,
            metadata={"CreationDate": None},
            bbox_inches="tight",
            pad_inches=THEMES[theme]["pad"],
        )
        plt.close(fig)


def export(figures, names, fmt, theme, output, suffix=""):
    """Write each named figure; skip those whose data does not exist yet."""
    written = []
    for name in names:
        use_theme(theme)
        try:
            fig = figures[name](theme)
        except MissingData as error:
            print(f"Skipped {name}: {error}")
            continue
        path = Path(output) / f"{name}{suffix}.{fmt}"
        save(fig, path, theme)
        written.append(path)
    return written


def run_plots(figures, config):
    if config["list"]:
        print("\n".join(figures))
        return []
    unknown = set(config["names"]) - set(figures)
    if unknown:
        raise ValueError(
            f"Unknown figures: {', '.join(sorted(unknown))}; use list=true"
        )
    if config["format"] not in FORMATS:
        raise ValueError(f"Unsupported format: {config['format']}")
    if config["theme"] not in config["themes"]:
        raise ValueError(f"Unknown theme: {config['theme']}")
    previous_data = dict(DATASETS)
    DATASETS.clear()
    DATASETS.update(config["data"])
    previous = dict(THEMES)
    THEMES.clear()
    THEMES.update(config["themes"])
    try:
        paths = export(
            figures,
            config["names"] or list(figures),
            config["format"],
            config["theme"],
            config["output"],
        )
        for path in paths:
            print(path)
        return paths
    finally:
        DATASETS.clear()
        DATASETS.update(previous_data)
        THEMES.clear()
        THEMES.update(previous)


def main(figures, description):
    from harbor_adapter.experiment_config import cli

    cli("plot", lambda config: run_plots(figures, config))
