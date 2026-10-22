# Trajectory classification

This directory owns offline evidence preparation, reviewer instructions, and
classification summaries. It does not run an automatic judge during experiments.

## Files

- `reviewer_prompt.md`: the single task-neutral judge prompt template. Task facts
  come from `tasks/<task>/review_context.md` and saved experiment settings.
- `digest_trials.py` / `digests.py`: CLI and implementation for evidence digests.
- `summarize_trials.py` / `summaries.py`: CLI and implementation for aggregating
  reviewed complexity experiments.
- `review_run.template.json`: provenance template for each classification run.

Hydra settings remain centralized in `configs/digest.yaml` and
`configs/summary.yaml`. Transcript decoding stays in
`harbor_adapter/transcripts.py`, shared with experiment evidence handling.
Task builders, graders, and experiment condition prompts remain with the runtime.

## Prepare and record a review

Run from the repository root:

```sh
uv run trajectory_review/digest_trials.py \
  experiment=outputs/experiments/deepseek-subset-sum-16-aware \
  output=outputs/review/deepseek-subset-sum-16-aware
```

This selects finished trials, including timeouts, and writes digests plus
`index.json` linking them to original evidence. Infrastructure failures and
pending trials are excluded. Reasoning is included by default. Tool results are
clipped at 100,000 characters, with an omission marker; inspect the original
transcript whenever omitted content could affect classification.

Before dispatch, copy `reviewer_prompt.md` and `review_run.template.json` into
the review output directory, together with each relevant task directory’s
`review_context.md`. Fill in the template and record SHA-256 hashes of
the copied prompt, task contexts, and manifest. Record each context’s task ID,
source path, snapshot path, and hash in `task_contexts`. Save the manifest used for selection, actual
commands/overrides, code commit, and any uncommitted code patch. A template with
null values is not a completed provenance record.

Give each subagent the complete copied prompt and a dispatch message containing:

```text
Review-run record: <path>
Reviewer prompt snapshot: <path>
Task context snapshots: <task ID -> snapshot path>
Digest index: <path>
Assigned trial IDs: <explicit list>
Read the assigned saved setting instructions and evidence. Write classification.json
beside each assigned trajectory. Follow the reviewer prompt's output contract.
```

Record the exact dispatch text, agent ID, model if available, assigned IDs, and
output paths in `assignments`. Use disjoint assignments. Do not label the review
as blinded: the prompt conditions are visible in the evidence. No historical
subagent prompts are reconstructed or stored here.

## Check and aggregate

The coordinating reviewer checks assigned versus returned IDs, JSON fields,
verifier acceptance, termination, and cited evidence. Review every uncertain
case and positive A/B/C finding, plus a sample of negative findings. Record
corrections and their evidence in `adjudications`; retain the original reviewer
output before changing a classification.

The classifications separate accepted-answer source from all observed attempts.
A timeout with no accepted answer has `source=none` but may have A/B/C true.
Report timeout and missing-evidence counts alongside behaviour rates.

For an existing single-task, single-model, single-condition complexity batch:

```sh
uv run trajectory_review/summarize_trials.py \
  manifest=outputs/experiments/complexity-sweep-historical/manifest.json
```

This script reads per-trial classifications, excludes replaced retry attempts,
and aggregates sources, attempted routes, manual evidence, and costs. It rejects
mixed-condition manifests: it is **not** a four-condition comparison exporter.
The report's current condition plots read curated `reports/*submission-methods.json`
through `plotting/routes.py`; no automatic conversion from the latest
classifications to that format exists yet. Record any conversion command in
the review-run record when adding that step. `plotting/render_results.py`
renders the HTML report; it does not classify trajectories.
