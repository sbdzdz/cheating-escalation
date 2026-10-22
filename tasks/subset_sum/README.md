# Subset sum

Run `scripts/run_batch.py action=start experiments=subset-sum dry_run=true`, then resume
`outputs/experiments/subset-sum-sweep` to launch evaluations.

Configure exact integer bit length, set size, seeds, and optional solution size
in `configs/experiments/subset-sum.yaml`. Repeated values are allowed, indices
must be distinct, and any nonempty subset reaching the target is accepted.

The baseline sweep uses 2/4/8/16/32/64 bits at 64 integers and 4/8/16/32/64/128
integers at 32 bits. The shared 32-bit/64-integer case appears once.
Five seeds per combination produce 55 separate instance settings/trials.
Each seed is independently generated; repeated trials can be requested per seed.
An explicit `seed` on an instance takes precedence over the experiment’s `seeds`.
Seedless custom instances expand over `seeds` (default `[0]`); the original
fixture is included once. Instances can be inline mappings or JSON file paths
relative to the project root. Instance lists and seed lists used for expansion
must be nonempty.

The upstream fixture archive is used after checksum verification; see UPSTREAM.md.

`build.py` is a library used by the shared exporter and batch runner. To export
individual tasks, use `uv run scripts/export_harbor.py task=subset_sum 'questions=[4,5]'`.
Custom instances are supplied through the exporter’s `instance` Hydra setting.

Task-specific classification guidance is in [review_context.md](review_context.md);
the judge prompt and review tooling live in [trajectory_review](../../trajectory_review/README.md).
