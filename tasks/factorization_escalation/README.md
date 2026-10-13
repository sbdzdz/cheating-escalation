# Prime factorization task

Adapted from CheatBench; see [UPSTREAM.md](UPSTREAM.md) for provenance.

- `build.py` generates the task prompt, repository fixtures, synthetic history,
  and planted answer logs. It accepts custom semiprimes through the exporter.
- `grader.py` implements the factor-checking tool, with 50 valid checks and
  persistent acceptance of a correct pair. Harbor owns transport and scoring.
- `judge_schema.py` preserves the behavioral-review rubric. Review distinguishes
  answer access and attempts from the source of the submitted answer; checking
  already manually derived factors programmatically does not change their source.

Use `scripts/run_batch.py` for experiments, or `scripts/export_harbor.py` and
`scripts/run_factorization.py` for individual tasks. See the root README for commands.
No automatic LLM cheating judge or live agent-readable log observer runs here.

`data.jsonl` and `environment/files/` are generated, ignored build artifacts.
The builder recreates them as needed; they are not source inputs.
