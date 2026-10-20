"""Effort before the first cheating action in prime factorization, per condition."""

import functools
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullLocator

from plotting.common import MODELS, ROOT, main, plt, tip, use_theme
from plotting.routes import CONDITIONS, reviews


def iso_seconds(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def agent_minutes(trial_dir):
    execution = json.loads((trial_dir / "result.json").read_text())["agent_execution"]
    return (iso_seconds(execution["finished_at"]) - iso_seconds(execution["started_at"])) / 60


def deepseek_effort(row):
    run = ROOT / "outputs/harbor" / row["run_id"]
    annotation = json.loads((run / "annotation.json").read_text())
    trial_dir = next((run / "trials").glob("*/trajectory.json")).parent
    steps = json.loads((trial_dir / "trajectory.json").read_text())["steps"]
    events = json.loads((trial_dir / "transcript.json").read_text())["events"]
    first = min(e["trajectory_step"] for e in annotation["evidence"])
    first_ids = {
        c["tool_call_id"]
        for s in steps if s["step_id"] == first
        for c in s.get("tool_calls") or []
    }
    used, tokens = 0, None
    for event in events:
        update = event["payload"].get("update", {})
        if update.get("sessionUpdate") == "usage_update":
            used = update["used"]
        if tokens is None and update.get("toolCallId") in first_ids:
            tokens = used
    return {
        "calls": sum(len(s.get("tool_calls") or []) for s in steps if s["step_id"] < first),
        "tokens": tokens,
        "minutes": agent_minutes(trial_dir),
    }


def glm_effort(row):
    trial_dir = (ROOT / row["transcript"]).parent
    minutes = agent_minutes(trial_dir)
    if not row["tool_evidence"]:
        return {"calls": None, "tokens": None, "minutes": minutes}
    events = json.loads((ROOT / row["transcript"]).read_text())["events"]
    call_id = min(row["tool_evidence"], key=lambda e: e["seq"])["tool_call_id"]
    scheduled = [
        e for e in events
        if e.get("type") == "tool.updated" and e["payload"].get("kind") == "scheduled"
    ]
    first = next(e["seq"] for e in scheduled if e["payload"]["toolCallId"] == call_id)
    issued = next(
        e["seq"] for e in events
        if e.get("type") == "model.streaming"
        and e["payload"].get("kind") == "tool_call"
        and e["payload"].get("toolCallId") == call_id
    )
    # Context size of the model call that issued the first cheating tool call.
    usage = next(
        e["payload"]["usage"] for e in events
        if e["seq"] > issued and e.get("type") == "session.updated"
        and "contextWindow" in e["payload"]
    )
    return {
        "calls": sum(e["seq"] < first for e in scheduled),
        "tokens": usage["totalTokens"],
        "minutes": minutes,
    }


@functools.cache
def efforts():
    """Per model and condition, one entry per trial; first-cheat metrics only when the answer came from cheating."""
    rows = reviews("factorization")
    measure = {"deepseek": deepseek_effort, "glm": glm_effort}
    data = {}
    for model in MODELS:
        data[model] = {}
        for condition, _ in CONDITIONS:
            data[model][condition] = []
            for r in rows:
                if r["batch"] != f"{model}-{condition}":
                    continue
                effort = measure[model](r)
                cheated = r["submission_method"] in "ABC"
                if not cheated:
                    effort = dict(effort, calls=None, tokens=None)
                data[model][condition].append(dict(effort, cheated=cheated))
    return data


def median(xs):
    xs = sorted(xs)
    return (xs[(len(xs) - 1) // 2] + xs[len(xs) // 2]) / 2


def figure(theme_name, model):
    theme = use_theme(theme_name)
    data = efforts()
    # Both models share each metric's scale.
    values = lambda key: [t[key] for m in data.values() for ts in m.values() for t in ts if t[key] is not None]
    calls_max = 5 * math.ceil(max(values("calls")) / 5)
    tokens_max = 20000 * math.ceil(max(values("tokens")) / 20000)
    ticks = (0.5, 1, 2, 5, 10, 30, 60, 120, 240)
    time_ticks = ticks[: next(i for i, t in enumerate(ticks) if t >= max(values("minutes"))) + 1]
    metrics = [
        ("calls", "Tool calls before first cheat", (0, calls_max), False,
         [(t, str(t)) for t in range(0, calls_max + 1, calls_max // 5)], lambda v: f"{v:g}"),
        ("tokens", "Context tokens at first cheat", (0, tokens_max), False,
         [(t, f"{t // 1000}k") for t in range(0, tokens_max + 1, tokens_max // 5)], lambda v: f"{v / 1000:.1f}k"),
        ("minutes", "Agent wall time (minutes, log)", (time_ticks[0], time_ticks[-1]), True,
         [(t, f"{t:g}") for t in time_ticks], lambda v: f"{v:.1f} min"),
    ]
    fig, axes = plt.subplots(
        1, 3, sharey=True, layout="constrained",
        figsize=(theme["width"], theme["chrome"] + 0.3 + len(CONDITIONS) * theme["row"]),
    )
    fig.get_layout_engine().set(wspace=0.12)
    for ax, (key, label, limits, log, metric_ticks, fmt) in zip(axes, metrics):
        if log:
            ax.set_xscale("log")
        ax.set_xlim(*limits)
        ax.xaxis.set_major_locator(FixedLocator([t for t, _ in metric_ticks]))
        ax.set_xticklabels([text for _, text in metric_ticks])
        ax.xaxis.set_minor_locator(NullLocator())
        ax.tick_params(length=0, axis="x", colors=theme["muted"])
        ax.tick_params(length=0, axis="y", pad=8)
        ax.grid(axis="x", color=theme["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(label, fontweight="bold", pad=theme["font"])
        for i, (condition, condition_label) in enumerate(CONDITIONS):
            shown = [t for t in data[model][condition] if t[key] is not None]
            for j, t in enumerate(shown):
                x = max(t[key], limits[0]) if log else t[key]
                # A fixed jitter keeps overlapping trials visible and the figure reproducible.
                y = i + (((j * 7) % 21) - 10) / 60
                dot = ax.scatter([x], [y], s=theme["font"] * 2, alpha=0.85, linewidths=0,
                                 color=theme["used"] if t["cheated"] else theme["attempted"], zorder=3)
                tip(fig, dot, f"{condition_label}: {fmt(t[key])}")
            if shown:
                m = median([t[key] for t in shown])
                (line,) = ax.plot([m, m], [i - 0.27, i + 0.27], color=theme["text"], linewidth=3, zorder=4)
                tip(fig, line, f"{condition_label}: median {fmt(m)} (n = {len(shown)})")
            else:
                ax.text(0.5, i, "no cheating", transform=ax.get_yaxis_transform(), ha="center",
                        va="center", color=theme["muted"])
    axes[0].set_ylim(len(CONDITIONS) - 0.5, -0.5)
    axes[0].set_yticks(range(len(CONDITIONS)), [label for _, label in CONDITIONS])
    fig.legend(
        handles=[
            Line2D([], [], linestyle="", marker="o", color=theme["used"], label="Cheated"),
            Line2D([], [], linestyle="", marker="o", color=theme["attempted"], label="Did not cheat (wall time only)"),
            Line2D([], [], color=theme["text"], linewidth=3, label="Median"),
        ],
        loc="outside upper left", ncols=3, frameon=False, handlelength=1.2,
    )
    return fig


FIGURES = {f"effort-{model}": (lambda theme, m=model: figure(theme, m)) for model in MODELS}


if __name__ == "__main__":
    main(FIGURES, __doc__)
