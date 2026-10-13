# Subset sum

Run `scripts/run_batch.py start experiments=subset-sum --dry-run`, then resume
`outputs/experiments/subset-sum-sweep` to launch evaluations.

Configure exact integer bit length, set size, seeds, and optional solution size
in `configs/experiments/subset-sum.yaml`. Repeated values are allowed, indices
must be distinct, and any nonempty subset reaching the target is accepted.

The baseline sweep uses 4/8/16/32/64 bits at 64 integers and 8/16/32/64/128
integers at 32 bits. The shared 32-bit/64-integer case appears once.
Five seeds per combination produce 45 separate instance settings/trials.
Each seed is independently generated; repeated trials can be requested per seed.

The upstream fixture archive is used after checksum verification; see UPSTREAM.md.
