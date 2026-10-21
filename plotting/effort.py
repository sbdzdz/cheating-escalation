"""Effort before the first cheating action in prime factorization, per condition."""

import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullLocator

from plotting.common import DATASETS, MODELS, ROOT, main, plt, tip, use_theme
from plotting.routes import CONDITIONS, reviews


def iso_seconds(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def agent_minutes(trial_dir):
    execution = json.loads((trial_dir / "result.json").read_text())["agent_execution"]
    return (
        iso_seconds(execution["finished_at"]) - iso_seconds(execution["started_at"])
    ) / 60


def model_call_effort(transcript, evidence_ids):
    """Count issued tools before the model response containing the first evidence.

    Tools emitted in the same response share a context and have no established
    execution order. Usage is the issuing response's total context, not a sum
    over earlier requests (which would count repeated context multiple times).
    """
    used = 0
    for call in sorted(transcript["calls"], key=lambda c: c["index"]):
        response = call["response"]
        tools = response.get("tool_calls") or []
        if any(tool["id"] in evidence_ids for tool in tools):
            usage = response.get("usage") or {}
            tokens = usage.get("total_tokens")
            if tokens is None and all(
                k in usage for k in ("prompt_tokens", "completion_tokens")
            ):
                tokens = usage["prompt_tokens"] + usage["completion_tokens"]
            return {"calls": used, "tokens": tokens}
        used += len(tools)
    raise ValueError("Annotated tool calls are absent from the model-call transcript")


def deepseek_effort(row):
    run = ROOT / DATASETS["runs"] / row["run_id"]
    (trial_dir,) = (run / "trials").iterdir()
    minutes = agent_minutes(trial_dir)
    if row["submission_method"] not in ("A", "B", "C"):
        return {"calls": None, "tokens": None, "minutes": minutes}
    annotation_path = run / "annotation.json"
    evidence = row.get("tool_evidence")
    if evidence is None:
        evidence = json.loads(annotation_path.read_text())["evidence"]
    transcript = json.loads((trial_dir / "transcript.json").read_text())
    trajectory_path = trial_dir / "trajectory.json"
    steps = (
        json.loads(trajectory_path.read_text())["steps"]
        if trajectory_path.exists()
        else []
    )
    if transcript.get("format") == "model-calls-v1":
        evidence_ids = {e["tool_call_id"] for e in evidence if e.get("tool_call_id")}
        step_ids = {e["trajectory_step"] for e in evidence if "trajectory_step" in e}
        if step_ids and not steps:
            raise ValueError(
                "Trajectory-step evidence requires the original trajectory; use tool_call_id for model-call transcripts"
            )
        evidence_ids.update(
            c["tool_call_id"]
            for step in steps
            if step["step_id"] in step_ids
            for c in step.get("tool_calls") or []
        )
        return dict(model_call_effort(transcript, evidence_ids), minutes=minutes)
    if transcript.get("format") not in (None, "acp-events-v1"):
        raise ValueError(
            f"Unsupported DeepSeek effort transcript format: {transcript.get('format')}"
        )
    events = transcript["events"]
    first = min(e["trajectory_step"] for e in evidence)
    first_ids = {
        c["tool_call_id"]
        for s in steps
        if s["step_id"] == first
        for c in s.get("tool_calls") or []
    }
    if not first_ids:
        raise ValueError("Annotated trajectory step has no tool calls")
    used, tokens = None, None
    for event in events:
        update = event["payload"].get("update", {})
        if update.get("sessionUpdate") == "usage_update":
            used = update["used"]
        if tokens is None and update.get("toolCallId") in first_ids:
            tokens = used
    return {
        "calls": sum(
            len(s.get("tool_calls") or []) for s in steps if s["step_id"] < first
        ),
        "tokens": tokens,
        "minutes": minutes,
    }


def glm_effort(row):
    trial_dir = (ROOT / row["transcript"]).parent
    minutes = agent_minutes(trial_dir)
    if not row["tool_evidence"]:
        return {"calls": None, "tokens": None, "minutes": minutes}
    transcript = json.loads((ROOT / row["transcript"]).read_text())
    if transcript.get("format") == "model-calls-v1":
        evidence_ids = {e["tool_call_id"] for e in row["tool_evidence"]}
        return dict(model_call_effort(transcript, evidence_ids), minutes=minutes)
    if transcript.get("format") not in (None, "zcode-events-v1"):
        raise ValueError(
            f"Unsupported GLM effort transcript format: {transcript.get('format')}"
        )
    events = transcript["events"]
    call_id = min(row["tool_evidence"], key=lambda e: e["seq"])["tool_call_id"]
    scheduled = [
        e
        for e in events
        if e.get("type") == "tool.updated" and e["payload"].get("kind") == "scheduled"
    ]
    first = next(e["seq"] for e in scheduled if e["payload"]["toolCallId"] == call_id)
    issued = next(
        e["seq"]
        for e in events
        if e.get("type") == "model.streaming"
        and e["payload"].get("kind") == "tool_call"
        and e["payload"].get("toolCallId") == call_id
    )
    # Context size of the model call that issued the first cheating tool call.
    usage = next(
        e["payload"]["usage"]
        for e in events
        if e["seq"] > issued
        and e.get("type") == "session.updated"
        and "contextWindow" in e["payload"]
    )
    return {
        "calls": sum(e["seq"] < first for e in scheduled),
        "tokens": usage["totalTokens"],
        "minutes": minutes,
    }


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
                cheated = r["submission_method"] in ("A", "B", "C")
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
    values = lambda key: [
        t[key]
        for m in data.values()
        for ts in m.values()
        for t in ts
        if t[key] is not None
    ]
    calls_max = max(5, 5 * math.ceil(max(values("calls"), default=0) / 5))
    tokens_max = max(20000, 20000 * math.ceil(max(values("tokens"), default=0) / 20000))
    ticks = [0.5, 1, 2, 5, 10, 30, 60, 120, 240]
    max_minutes = max(values("minutes"), default=1)
    while ticks[-1] < max_minutes:
        ticks.append(ticks[-1] * 2)
    time_ticks = ticks[
        : max(1, next(i for i, t in enumerate(ticks) if t >= max_minutes)) + 1
    ]
    metrics = [
        (
            "calls",
            "Tool calls before first cheat",
            (0, calls_max),
            False,
            [(t, str(t)) for t in range(0, calls_max + 1, calls_max // 5)],
            lambda v: f"{v:g}",
        ),
        (
            "tokens",
            "Context tokens at first cheat",
            (0, tokens_max),
            False,
            [(t, f"{t // 1000}k") for t in range(0, tokens_max + 1, tokens_max // 5)],
            lambda v: f"{v / 1000:.1f}k",
        ),
        (
            "minutes",
            "Agent wall time (minutes, log)",
            (time_ticks[0], time_ticks[-1]),
            True,
            [(t, f"{t:g}") for t in time_ticks],
            lambda v: f"{v:.1f} min",
        ),
    ]
    fig, axes = plt.subplots(
        1,
        3,
        sharey=True,
        layout="constrained",
        figsize=(
            theme["width"],
            theme["chrome"] + 0.3 + len(CONDITIONS) * theme["row"],
        ),
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
                dot = ax.scatter(
                    [x],
                    [y],
                    s=theme["font"] * 2,
                    alpha=0.85,
                    linewidths=0,
                    color=theme["used"] if t["cheated"] else theme["attempted"],
                    zorder=3,
                )
                tip(fig, dot, f"{condition_label}: {fmt(t[key])}")
            if shown:
                m = median([t[key] for t in shown])
                (line,) = ax.plot(
                    [m, m],
                    [i - 0.27, i + 0.27],
                    color=theme["text"],
                    linewidth=3,
                    zorder=4,
                )
                tip(fig, line, f"{condition_label}: median {fmt(m)} (n = {len(shown)})")
            else:
                ax.text(
                    0.5,
                    i,
                    "no measurements"
                    if any(t["cheated"] for t in data[model][condition])
                    else "no cheating",
                    transform=ax.get_yaxis_transform(),
                    ha="center",
                    va="center",
                    color=theme["muted"],
                )
    axes[0].set_ylim(len(CONDITIONS) - 0.5, -0.5)
    axes[0].set_yticks(range(len(CONDITIONS)), [label for _, label in CONDITIONS])
    fig.legend(
        handles=[
            Line2D(
                [], [], linestyle="", marker="o", color=theme["used"], label="Cheated"
            ),
            Line2D(
                [],
                [],
                linestyle="",
                marker="o",
                color=theme["attempted"],
                label="Did not cheat (wall time only)",
            ),
            Line2D([], [], color=theme["text"], linewidth=3, label="Median"),
        ],
        loc="outside upper left",
        ncols=3,
        frameon=False,
        handlelength=1.2,
    )
    return fig


FIGURES = {
    f"effort-{model}": (lambda theme, m=model: figure(theme, m)) for model in MODELS
}


if __name__ == "__main__":
    main(FIGURES, __doc__)
