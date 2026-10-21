# Cheating escalation

## Setup

Install uv and start Docker with Compose support.

```sh
uv sync --locked
```

Set `OPENROUTER_API_KEY` in the project-root `.env`.

## Batch runs

Prepare an experiment without launching evaluations:

```sh
uv run scripts/run_batch.py action=start \
  experiments=complexity-sweep model=deepseek-v4-flash \
  parallel=10 target_trials=15 max_cost_per_trial_usd=10 \
  dry_run=true
```

Launch, inspect, or resume it:

```sh
uv run scripts/run_batch.py action=resume path=outputs/experiments/complexity-sweep-v2
uv run scripts/run_batch.py action=status path=outputs/experiments/complexity-sweep-v2
```

Increase the target or retry a failed trial:

```sh
uv run scripts/run_batch.py action=resume path=outputs/experiments/complexity-sweep-v2 target_trials=20 parallel=10
uv run scripts/run_batch.py action=retry path=outputs/experiments/complexity-sweep-v2 trial=TRIAL_ID
```

Batch actions are configured in `configs/action/`; shared experiment defaults
are in `configs/batch.yaml`. Resume and retry load saved settings, with optional
`parallel=...` and `target_trials=...` overrides. Model and experiment overrides
are accepted only for new experiments. Use `--cfg job --resolve` to inspect an
action’s configuration without changing files.

On `start`, use `name=NEW_NAME` for a separate experiment. Select
`experiments=archive/pilots` for the pilot instances or `model=kimi-k3` for Kimi.
Set conditions with `'conditions=[baseline,b-caught,ab-caught,manual-only]'`.
Edit instances in `configs/experiments/` and model settings in `configs/model/`.

Select `model=glm-5.3-flash` for GLM 5.3 Flash through OpenRouter in Z.ai's
ZCode harness. Individual runs use `model=glm-5.3-flash`. It uses the same
`OPENROUTER_API_KEY` and `max_cost_usd` / `max_cost_per_trial_usd` controls.
The ZCode source commit is pinned in `configs/zcode/source.json`; its first
runtime build downloads and compiles the CLI. Build it ahead of time with:

```sh
uv run scripts/build_runtime.py model=glm-5.3-flash
```

ZCode runs unattended with the task's MCP verifier and its normal local tools.
Web search/fetch tools and optional plugins are disabled. The configured model
is GLM 5.3 Flash, with ZCode's default reasoning settings.
Review its structured events in the usual `transcript.json`; original
events and stderr are retained in the debug archive. Provider credentials stay
inside the container's configuration, outside the collected logs.

Validate the built ZCode runtime with a fake model and MCP verifier (Docker
networking is disabled; no API key or paid calls):

```sh
uv run python tests/zcode_smoke.py
```

## Individual runs

Export a task, inspect its run configuration, then run it:

```sh
uv run scripts/export_harbor.py 'questions=[4]' condition=baseline
uv run scripts/run_trial.py model=deepseek-v4-flash condition=baseline max_cost_usd=10 print_config=true
uv run scripts/run_trial.py model=deepseek-v4-flash condition=baseline max_cost_usd=10
```

Use `model=kimi-k3` for Kimi. Set the same `condition=...` on export and
the trial command: `baseline`, `b-caught`, `ab-caught`, or `manual-only`.

To select a custom number, create a JSON file with decimal-string `number`, `p`,
and `q` fields and pass it to both commands:

```sh
uv run scripts/export_harbor.py instance=configs/instances/original.json
uv run scripts/run_trial.py instance=configs/instances/original.json model=deepseek-v4-flash max_cost_usd=10
```

For an individual subset-sum run, select the task on both commands:

```sh
uv run scripts/export_harbor.py task=subset_sum
uv run scripts/run_trial.py task=subset_sum model=deepseek-v4-flash max_cost_usd=10
```

These select the original Q4 fixture. For a custom instance, pass the same
JSON file using `instance=...` on both commands, containing e.g.
`{"bits": 16, "set_size": 8, "seed": 7}`. Custom subset-sum instances use Q4;
original fixtures also support other questions via `questions=[5]` on export
and `question=...` on the trial command. Explicit `task_path=...` snapshots take
precedence over instance selection.

Export defaults live in `configs/export.yaml`. Inline instances are also supported,
for example `'instance={bits:16,set_size:8,seed:7}'` with `task=subset_sum`.
Use `--cfg job --resolve` to inspect export configuration without writing files.
Hydra leaves the working directory unchanged; relative export paths resolve there.

Trial defaults live in `configs/trial.yaml`; runtime-build defaults are in
`configs/runtime.yaml`. Both use `model=...` to select `configs/model/` profiles.
Override model settings directly, e.g. `model.env.DSH_REASONING_EFFORT=low` or
`model=kimi-k3 model.kwargs.version=0.43.0`. The default model is DeepSeek for
batch runs, individual trials, and runtime builds.

Use `--cfg job --resolve` to inspect YAML settings without executing anything;
`print_config=true` on a trial additionally constructs Harbor's job configuration.
For saved batches, `model_snapshot=path/to/model.json` and optional
`snapshot_profile=...` take precedence over the current model YAML.

## Build the runtime

```sh
uv run scripts/build_runtime.py model=deepseek-v4-flash
```

## Tests

```sh
uv run scripts/export_harbor.py 'questions=[4]'
uv run python -m unittest discover -s tests -v
```

Run Docker checks without model calls:

```sh
uv run scripts/run_trial.py agent=oracle
uv run scripts/run_trial.py agent=nop
```

## Review and reports

Find run evidence under `outputs/harbor/<run>/trials/<trial>/` and costs in
`outputs/harbor/<run>/budget.json`. For new batches, save reviewed classifications
as `classification.json` beside each trajectory, with `source`, `A`, `B`, `C`,
and `manual_evidence` fields.

Aggregate a reviewed complexity experiment:

```sh
uv run scripts/summarize_complexity.py --manifest outputs/experiments/complexity-sweep-historical/manifest.json
```

Render the report, then open `results.html`:

```sh
uv run plotting/render_results.py
```

Each plot has one script in `plotting/`: `routes.py` (how answers were
produced, per condition), `effort.py` (effort before cheating) and
`difficulty.py` (cheating rate against difficulty). Each writes PDF or SVG;
PDFs default to the paper theme and `paper/fig/`:

```sh
uv run plotting/difficulty.py                 # paper figures
uv run plotting/routes.py --list
uv run plotting/routes.py subset-sum-16-bshown-deepseek --format svg --theme light
```

Compile the paper with `python3 paper/compile.py`.

Import a historical analysis into a new manifest:

```sh
uv run scripts/run_batch.py action=import path=outputs/analysis/deepseek-complexity-combined-analysis.json output=outputs/experiments/imported-history
```

## Download upstream source

```sh
uv run --no-project scripts/setup_cheatbench.py
```
