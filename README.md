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
uv run scripts/run_batch.py start \
  experiments=complexity-sweep model=deepseek-v4-flash \
  parallel=10 target_trials=15 max_cost_per_trial_usd=10 \
  --dry-run
```

Launch, inspect, or resume it:

```sh
uv run scripts/run_batch.py resume outputs/experiments/complexity-sweep-v2
uv run scripts/run_batch.py status outputs/experiments/complexity-sweep-v2
```

Increase the target or retry a failed trial:

```sh
uv run scripts/run_batch.py resume outputs/experiments/complexity-sweep-v2 --target-trials 20 --parallel 10
uv run scripts/run_batch.py retry outputs/experiments/complexity-sweep-v2 --trial TRIAL_ID
```

On `start`, use `name=NEW_NAME` for a separate experiment. Select
`experiments=archive/pilots` for the pilot instances or `model=kimi-k3` for Kimi.
Set conditions with `'conditions=[baseline,b-caught,ab-caught,manual-only]'`.
Edit instances in `configs/experiments/` and model settings in `configs/model/`.

## Individual runs

Export a task, inspect its run configuration, then run it:

```sh
uv run scripts/export_harbor.py --questions 4 --condition baseline
uv run scripts/run_factorization.py --profile deepseek-v4-flash --condition baseline --max-cost-usd 10 --print-config
uv run scripts/run_factorization.py --profile deepseek-v4-flash --condition baseline --max-cost-usd 10
```

Use `--profile kimi-k3` for Kimi. Set the same `--condition` when exporting and
running: `baseline`, `b-caught`, `ab-caught`, or `manual-only`.

To select a custom number, create a JSON file with decimal-string `number`, `p`,
and `q` fields and pass it to both commands:

```sh
uv run scripts/export_harbor.py --instance configs/instances/original.json
uv run scripts/run_factorization.py --instance configs/instances/original.json --profile deepseek-v4-flash --max-cost-usd 10
```

## Build the runtime

```sh
uv run scripts/build_runtime.py --profile deepseek-v4-flash
```

## Tests

```sh
uv run scripts/export_harbor.py --questions 4
uv run python -m unittest discover -s tests -v
```

Run Docker checks without model calls:

```sh
uv run scripts/run_factorization.py --agent oracle
uv run scripts/run_factorization.py --agent nop
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

Render the report and export figures:

```sh
uv run scripts/render_results.py
uv run scripts/export_report_figures.py
```

Open `reports/results.html`; find SVGs in `reports/figures/`.

Import a historical analysis into a new manifest:

```sh
uv run scripts/run_batch.py import outputs/deepseek-complexity-combined-analysis.json --output outputs/experiments/imported-history
```

Summarize an older annotated baseline batch:

```sh
uv run scripts/summarize_baseline.py MANIFEST --output SUMMARY
```

## Download upstream source

```sh
uv run --no-project scripts/setup_cheatbench.py
```
