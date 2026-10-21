# Prime factorization task

Adapted from CheatBench; see [UPSTREAM.md](UPSTREAM.md) for provenance.

- `build.py` generates the task prompt, repository fixtures, synthetic history,
  and planted answer logs. It is a library used by the shared exporter, which
  accepts custom semiprimes and question selection through Hydra.
- `grader.py` implements the factor-checking tool, with 50 valid checks and
  persistent acceptance of a correct pair. Harbor owns transport and scoring.
- `judge_schema.py` preserves the behavioral-review rubric. Review distinguishes
  answer access and attempts from the source of the submitted answer; checking
  already manually derived factors programmatically does not change their source.

Use `scripts/run_batch.py` for experiments, or `scripts/export_harbor.py` and
`scripts/run_trial.py` for individual tasks. See the root README for commands.
No automatic LLM cheating judge or live agent-readable log observer runs here.

`data.jsonl` and `environment/files/` are generated, ignored build artifacts.
The exporter builds them in a temporary directory; they are not source inputs.
For example: `uv run scripts/export_harbor.py task=factorization 'questions=[24,25]'`.
