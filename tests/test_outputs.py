import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from harbor_adapter.outputs import compact_job


class OutputTests(unittest.TestCase):
    def test_compaction_preserves_evidence_and_archives_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            files = {
                "debug/result.json": "{}",
                "budget.json": '{"spent_usd":"0.2"}',
                "debug/config.json": "{}",
                "debug/trial/result.json": "{}",
                "debug/trial/agent/kimi-code.json": '{"events":[]}',
                "debug/trial/agent/.kimi-code/session.json": '{"internal":true}',
                "debug/trial/artifacts/evidence/state.json": '{"score":1}',
                "annotation.json": '{"transcript":"debug/trial/agent/kimi-code.json"}',
            }
            for name, content in files.items():
                path = job / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            compact_job(job)
            self.assertFalse((job / "debug").exists())
            self.assertEqual(
                (job / "trials/trial/verifier.json").read_text(), '{"score":1}'
            )
            self.assertEqual(
                json.loads((job / "annotation.json").read_text())["transcript"],
                "trials/trial/transcript.json",
            )
            with ZipFile(job / ".debug/debug.zip") as archive:
                for name, content in files.items():
                    if name.startswith("debug/"):
                        self.assertEqual(archive.read(name).decode(), content)
            compact_job(job)
            self.assertTrue((job / "trials/trial/transcript.json").exists())

    def test_keep_debug_and_failed_run(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "debug").mkdir()
            (job / "debug/job.log").write_text("setup failed")
            compact_job(job, keep_debug=True)
            self.assertTrue((job / "debug/job.log").exists())
            self.assertFalse((job / ".debug/debug.zip").exists())
            compact_job(job)
            with ZipFile(job / ".debug/debug.zip") as archive:
                self.assertEqual(archive.read("debug/job.log"), b"setup failed")

    def test_standard_call_log_replaces_harness_transcripts(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            call = {
                "type": "call",
                "index": 0,
                "parent": None,
                "new_messages": [],
                "response": {},
            }
            files = {
                "model-calls.jsonl": json.dumps(call) + "\n",
                "debug/trial/result.json": "{}",
                "debug/trial/agent/trajectory.json": '{"steps":[]}',
                "debug/trial/agent/zcode-events.jsonl": "{}\n",
                "debug/trial/artifacts/evidence/state.json": "{}",
            }
            for name, content in files.items():
                path = job / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            compact_job(job)
            trial = job / "trials/trial"
            self.assertEqual(
                sorted(p.name for p in trial.iterdir()),
                ["result.json", "transcript.json", "verifier.json"],
            )
            transcript = json.loads((trial / "transcript.json").read_text())
            self.assertEqual(
                (transcript["format"], transcript["calls"]), ("model-calls-v1", [call])
            )
            self.assertFalse((job / "model-calls.jsonl").exists())
            with ZipFile(job / ".debug/debug.zip") as archive:
                self.assertIn("debug/model-calls.jsonl", archive.namelist())
                self.assertIn("debug/trial/agent/trajectory.json", archive.namelist())
