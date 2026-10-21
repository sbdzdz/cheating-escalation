"""How agents produced their submitted answer, per condition: one bar per method."""

import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matplotlib.patches import Patch

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

LABELS = {
    "factorization": ["Manual factoring", "Programmatic factoring", "Answer lookup"],
    "subset-sum": ["Manual search", "Programmatic search", "Answer lookup"],
    "joint": ["Manual work", "Programmatic solving", "Answer lookup"],
}
CONDITIONS = [
    ("baseline", "Baseline"),
    ("b-caught", "Answer lookup penalised"),
    ("ab-caught", "Both methods penalised"),
]
USED, ATTEMPTED = "Produced submitted answer", "Attempted or accessed only"
ROUTE_KEYS = ["A_prohibited_computation", "B_answer_key_access", "C_scoring_tampering"]


def reviews(name):
    rows = []
    for relative in DATASETS["reviews"][name]:
        path = ROOT / relative
        if not path.exists():
            raise MissingData(f"{relative} does not exist")
        rows += json.loads(path.read_text())["trials"]
    return rows


def route_counts(rows, batch, subset=False):
    """Trials per method that produced the answer, and that only tried it.

    Subset-sum reviews record manual work as `manual_attempt` and count a timed-out
    trial's methods as attempts only.
    """
    manual_key = "manual_attempt" if subset else "manual_factoring_attempt"
    selected = [r for r in rows if r["batch"] == batch]
    if not selected:
        raise MissingData(f"no reviewed trials for {batch}")
    n = len(selected)
    annotations = [
        r
        if "observed_routes" in r
        else json.loads(
            (ROOT / DATASETS["runs"] / r["run_id"] / "annotation.json").read_text()
        )
        for r in selected
    ]
    timed_out = [subset and a["termination"] == "timeout" for a in annotations]
    methods = [
        "none" if t else r["submission_method"] for r, t in zip(selected, timed_out)
    ]
    used = [sum(m == "manual" for m in methods)] + [
        sum(m == k for m in methods) for k in "ABC"
    ]
    attempted = [
        sum(
            (r[manual_key] or r["submission_method"] == "manual") and m != "manual"
            for r, m in zip(selected, methods)
        )
    ] + [
        sum(
            (a["observed_routes"][key] or r["submission_method"] == k) and m != k
            for r, a, m in zip(selected, annotations, methods)
        )
        for k, key in zip("ABC", ROUTE_KEYS)
    ]
    # Trials with no accepted answer that attempted no method at all.
    idle = sum(
        r["submission_method"] == "none"
        and not r[manual_key]
        and not any(a["observed_routes"][key] for key in ROUTE_KEYS)
        for r, a in zip(selected, annotations)
    )
    interrupted = sum(
        a["termination"] != "completed" and not t
        for a, t in zip(annotations, timed_out)
    )
    notes = []
    if interrupted:
        kind = (
            "API-interrupted"
            if all(a["termination"] in ("completed", "api_error") for a in annotations)
            else "interrupted"
        )
        notes.append(
            f"Includes {interrupted} {kind} {'trial' if interrupted == 1 else 'trials'}; "
            f"percentages use all {n} trials."
        )
    if any(timed_out):
        count = sum(timed_out)
        notes.append(
            f"Includes {count} timed-out {'trial' if count == 1 else 'trials'}"
            " (5-minute limit), shown as attempts only."
        )
    without_submission = sum(
        r["submission_method"] == "none" and a["termination"] == "completed"
        for r, a in zip(selected, annotations)
    )
    if without_submission:
        notes.append(f"{without_submission} completed without an accepted submission.")
    return dict(n=n, used=used, attempted=attempted, idle=idle, note=" ".join(notes))


def pooled(*counts):
    return dict(
        n=sum(c["n"] for c in counts),
        used=[sum(v) for v in zip(*(c["used"] for c in counts))],
        attempted=[sum(v) for v in zip(*(c["attempted"] for c in counts))],
        idle=sum(c["idle"] for c in counts),
        note="",
    )


def figure(theme_name, panels, labels, idle=True):
    """One panel per (title, counts); one row per method, plus trials that attempted none."""
    theme = use_theme(theme_name)
    show_idle = idle and any(c["idle"] for _, c in panels)
    rows = labels + ["No method attempted"] * show_idle
    titled = any(title for title, _ in panels)
    fig, axes = plt.subplots(
        1,
        len(panels),
        sharey=True,
        squeeze=False,
        layout="constrained",
        figsize=(
            theme["width"],
            theme["chrome"] + titled * 0.3 + len(rows) * theme["row"],
        ),
    )
    fig.get_layout_engine().set(wspace=0.12)
    # A paper column fits fewer tick labels and only short title lines.
    steps = 2 if theme_name == "paper" else 5
    for ax, (title, counts) in zip(axes[0], panels):
        n = counts["n"]
        for i, label in enumerate(labels):
            assert 0 <= counts["used"][i] + counts["attempted"][i] <= n
            left = 0
            for value, color, description in (
                (counts["used"][i], theme["used"], USED),
                (counts["attempted"][i], theme["attempted"], ATTEMPTED),
            ):
                if value:
                    (bar,) = ax.barh(i, value / n, left=left, height=0.53, color=color)
                    where = f"{title}: " if title else ""
                    tip(
                        fig,
                        bar,
                        f"{where}{label}: {description}: {100 * value / n:g}% ({value}/{n} trials)",
                    )
                    left += value / n
        if show_idle and counts["idle"]:
            (bar,) = ax.barh(
                len(labels),
                counts["idle"] / n,
                height=0.53,
                color=theme["background"],
                edgecolor=theme["muted"],
                linewidth=1.2,
            )
            where = f"{title}: " if title else ""
            tip(
                fig,
                bar,
                f"{where}No method attempted: {100 * counts['idle'] / n:g}% ({counts['idle']}/{n} trials)",
            )
        ax.set_xlim(0, 1)
        ax.set_ylim(len(rows) - 0.5, -0.5)
        ax.set_xticks(
            [i / steps for i in range(steps + 1)],
            [f"{100 * i // steps}%" for i in range(steps + 1)],
        )
        ax.tick_params(length=0, axis="x", colors=theme["muted"])
        ax.tick_params(length=0, axis="y", pad=8)
        ax.grid(axis="x", color=theme["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_visible(False)
        if title:
            if theme_name == "paper":
                title = textwrap.fill(title, 15)
            ax.set_title(title, fontweight="bold", pad=theme["font"] * 2)
            ax.annotate(
                f"n = {n}",
                (0.5, 1),
                xycoords="axes fraction",
                xytext=(0, 5),
                textcoords="offset points",
                ha="center",
                va="bottom",
                color=theme["muted"],
            )
    axes[0][0].set_yticks(range(len(rows)), rows)
    # The first method is the intended one; the rest are prohibited.
    for i, text in enumerate(axes[0][0].get_yticklabels()):
        text.set_color(
            theme["text"]
            if i == 0
            else theme["muted"]
            if i >= len(labels)
            else theme["flagged"]
        )
    fig.supxlabel("Percentage of trials", color=theme["muted"], fontsize=theme["font"])
    fig.legend(
        handles=[
            Patch(color=theme["used"], label=USED),
            Patch(color=theme["attempted"], label=ATTEMPTED),
        ],
        loc="outside upper left",
        ncols=2,
        frameon=False,
        handlelength=1,
        handleheight=1,
    )
    return fig


def conditions(model, rows, subset=False):
    return [
        (title, route_counts(rows, f"{model}-{c}", subset)) for c, title in CONDITIONS
    ]


def single(batch):
    return lambda theme: figure(
        theme,
        [(None, route_counts(reviews("factorization"), batch))],
        LABELS["factorization"],
        idle=False,
    )


def joint(model):
    factorization = conditions(model, reviews("factorization"))
    subset = conditions(model, reviews("subset-sum"), subset=True)
    return [(title, pooled(f, s)) for (title, f), (_, s) in zip(factorization, subset)]


def without_path(model):
    # The baseline has no record, so both record versions share its trials.
    rows = [
        r for r in reviews("subset-sum-16") if r["batch"] == f"{model}-baseline"
    ] + [
        dict(r, batch=r["batch"].replace(f"{model}-nopath-", f"{model}-"))
        for r in reviews("subset-sum-16-nopath")
    ]
    return conditions(model, rows, subset=True)


def lookup_shown(model):
    # Control: the lookup record without the penalty, beside both ends.
    return [
        ("Baseline", route_counts(reviews("subset-sum-16"), f"{model}-baseline", True)),
        (
            "Answer lookup shown",
            route_counts(
                reviews("subset-sum-16-bshown"), f"{model}-bshown-b-shown", True
            ),
        ),
        (
            "Answer lookup penalised",
            route_counts(
                reviews("subset-sum-16-nopath"), f"{model}-nopath-b-caught", True
            ),
        ),
    ]


FIGURES = {
    f"factorization-{batch}": single(batch)
    for batch in (
        "kimi-baseline",
        "deepseek-baseline",
        "glm-baseline",
        "deepseek-manual-only",
        "deepseek-b-caught",
        "glm-b-caught",
        "deepseek-ab-caught",
        "glm-ab-caught",
    )
}
for _model in MODELS:
    FIGURES |= {
        f"factorization-{_model}": lambda theme, m=_model: figure(
            theme, conditions(m, reviews("factorization")), LABELS["factorization"]
        ),
        f"subset-sum-{_model}": lambda theme, m=_model: figure(
            theme,
            conditions(m, reviews("subset-sum"), subset=True),
            LABELS["subset-sum"],
        ),
        f"joint-{_model}": lambda theme, m=_model: figure(
            theme, joint(m), LABELS["joint"]
        ),
        f"subset-sum-16-{_model}": lambda theme, m=_model: figure(
            theme,
            conditions(m, reviews("subset-sum-16"), subset=True),
            LABELS["subset-sum"],
        ),
    }
FIGURES |= {
    "subset-sum-16-nopath-deepseek": lambda theme: figure(
        theme, without_path("deepseek"), LABELS["subset-sum"]
    ),
    "subset-sum-16-bshown-deepseek": lambda theme: figure(
        theme, lookup_shown("deepseek"), LABELS["subset-sum"]
    ),
}


if __name__ == "__main__":
    main(FIGURES, __doc__)
