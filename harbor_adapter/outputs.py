"""Compact completed Harbor jobs into review files plus a debug archive."""

import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def compact_job(job: Path, *, keep_debug: bool = False) -> None:
    debug = job / "debug"
    if not debug.is_dir() or (job / ".debug/debug.zip").exists():
        return
    trial_dirs = sorted(p.parent for p in debug.glob("*/result.json"))
    if (debug / "result.json").exists():
        shutil.copy2(debug / "result.json", job / "result.json")
    mapping = {}
    for trial in trial_dirs:
        target = job / "trials" / trial.name
        target.mkdir(parents=True, exist_ok=True)
        for source, name in [
            ("result.json", "result.json"),
            ("agent/kimi-code.json", "transcript.json"),
            ("agent/trajectory.json", "trajectory.json"),
            ("artifacts/evidence/state.json", "verifier.json"),
        ]:
            if (trial / source).exists():
                shutil.copy2(trial / source, target / name)
                mapping[str((trial / source).relative_to(job))] = str(
                    (target / name).relative_to(job)
                )
        events = trial / "agent/acp-events.jsonl"
        if events.exists():
            transcript = {
                "format": "acp-events-v1",
                "events": [
                    json.loads(line)
                    for line in events.read_text().splitlines()
                    if line.strip()
                ],
            }
            (target / "transcript.json").write_text(
                json.dumps(transcript, indent=2) + "\n"
            )
            mapping[str(events.relative_to(job))] = str(
                (target / "transcript.json").relative_to(job)
            )
    annotation = job / "annotation.json"
    if annotation.exists():
        data = json.loads(annotation.read_text())
        if data.get("transcript") in mapping:
            data["transcript"] = mapping[data["transcript"]]
            annotation.write_text(json.dumps(data, indent=2) + "\n")
    if keep_debug:
        return
    archive = job / ".debug/debug.zip.tmp"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for file in sorted(debug.rglob("*")):
            if file.is_file():
                output.write(file, file.relative_to(job))
    with ZipFile(archive) as check:
        if check.testzip() is not None:
            raise ValueError("Debug archive verification failed")
    archive.replace(job / ".debug/debug.zip")
    shutil.rmtree(debug)


if __name__ == "__main__":
    import sys

    compact_job(Path(sys.argv[1]))
