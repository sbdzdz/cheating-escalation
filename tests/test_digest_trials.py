import json
import tempfile
import unittest
from pathlib import Path

from harbor_adapter.agents.transcript import export_transcript
from harbor_adapter.transcripts import entries_for_trial
from scripts.digest_trials import digest


class DigestTests(unittest.TestCase):
    def test_kimi_preserves_messages_tools_raw_output_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            source = trial / "transcript.txt"
            events = [
                {
                    "role": "assistant",
                    "reasoning_content": "private reasoning",
                    "content": "inspect files",
                    "tool_calls": [
                        {
                            "id": "read1",
                            "function": {
                                "name": "Read",
                                "arguments": '{"path":"answer.txt"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "read1", "content": "answer header"},
            ]
            source.write_text(
                "\n".join(map(json.dumps, events))
                + "\nraw tool output\n42\n{broken\n"
                + json.dumps({"role": "assistant", "content": "finished"})
                + "\n"
            )
            export_transcript(source)
            # A stale ACP trajectory must not override the declared Kimi format.
            (trial / "trajectory.json").write_text('{"steps": []}')
            spec = {
                "task": "factorization",
                "condition": "baseline",
                "instance": {"p": 3, "q": 5},
            }
            result = digest(trial, spec, "completed")
            expected = [
                "private reasoning",
                "inspect files",
                "TOOL Read",
                "answer.txt",
                "RESULT Read",
                "answer header",
                "raw tool output",
                "42",
                "{broken",
                "finished",
            ]
            positions = [result.index(text) for text in expected]
            self.assertEqual(positions, sorted(positions))
            without_reasoning = digest(trial, spec, "completed", reasoning=False)
            self.assertNotIn("private reasoning", without_reasoning)
            self.assertIn("raw tool output", without_reasoning)

    def test_unknown_format_rejected_even_with_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            (trial / "transcript.json").write_text(
                '{"format":"future-format","events":[]}'
            )
            (trial / "trajectory.json").write_text('{"steps": []}')
            with self.assertRaisesRegex(ValueError, "future-format"):
                list(entries_for_trial(trial))

    def test_legacy_trajectory_without_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            (trial / "trajectory.json").write_text(
                json.dumps(
                    {
                        "steps": [
                            {"message": "task setup"},
                            {
                                "message": "working",
                                "tool_calls": [
                                    {
                                        "tool_call_id": "call1",
                                        "function_name": "Read",
                                        "arguments": {"path": "answer.txt"},
                                    }
                                ],
                                "observation": {
                                    "results": [
                                        {
                                            "source_call_id": "call1",
                                            "content": "evidence",
                                        }
                                    ]
                                },
                            },
                        ]
                    }
                )
            )
            entries = list(entries_for_trial(trial))
            self.assertEqual(
                [label for label, _ in entries], ["SAY", "TOOL Read", "RESULT"]
            )
            self.assertEqual(entries[-1][1], "evidence")

    def test_model_calls_take_precedence_and_keep_unparsed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            (trial / "trajectory.json").write_text('{"steps": []}')
            transcript = {
                "format": "model-calls-v1",
                "calls": [
                    {
                        "index": 0,
                        "parent": None,
                        "new_messages": [],
                        "response": {
                            "content": "model evidence",
                            "errors": ["failed call"],
                        },
                    }
                ],
                "unparsed_lines": ["partial record"],
            }
            (trial / "transcript.json").write_text(json.dumps(transcript))
            self.assertEqual(
                list(entries_for_trial(trial)),
                [
                    ("SAY", "model evidence"),
                    ("ERROR", '"failed call"'),
                    ("UNPARSED", "partial record"),
                ],
            )

    def test_zcode_stream_and_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp)
            transcript = {
                "format": "zcode-events-v1",
                "events": [
                    {
                        "seq": 1,
                        "type": "model.streaming",
                        "payload": {"kind": "text_delta", "delta": "working"},
                    },
                    {
                        "seq": 2,
                        "type": "model.streaming",
                        "payload": {"kind": "text_end"},
                    },
                    {
                        "seq": 3,
                        "type": "tool.updated",
                        "payload": {
                            "kind": "scheduled",
                            "toolName": "Read",
                            "input": {"path": "answer.txt"},
                        },
                    },
                    {
                        "seq": 4,
                        "type": "tool.updated",
                        "payload": {
                            "kind": "result",
                            "result": {"content": "evidence"},
                        },
                    },
                ],
            }
            (trial / "transcript.json").write_text(json.dumps(transcript))
            entries = list(entries_for_trial(trial))
            self.assertEqual(
                [label for label, _ in entries], ["SAY", "TOOL Read", "RESULT"]
            )
            self.assertEqual(entries[-1][1], "evidence")


class DigestConfigTests(unittest.TestCase):
    def test_cli_filters_finished_trials_and_applies_output_controls(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setting = root / "settings" / "setting1"
            setting.mkdir(parents=True)
            (setting / "setting.json").write_text(
                json.dumps(
                    {
                        "task": "factorization",
                        "condition": "baseline",
                        "instance": {"p": 3, "q": 5},
                    }
                )
            )
            folder = root / "run" / "trials" / "trial1"
            folder.mkdir(parents=True)
            (folder / "trajectory.json").write_text(
                json.dumps(
                    {
                        "steps": [
                            {"message": "setup"},
                            {
                                "message": "visible",
                                "tool_calls": [
                                    {
                                        "tool_call_id": "read1",
                                        "function_name": "Read",
                                        "arguments": {},
                                    }
                                ],
                                "observation": {
                                    "results": [
                                        {
                                            "source_call_id": "read1",
                                            "content": "abcdefghij",
                                        }
                                    ]
                                },
                            },
                        ]
                    }
                )
            )
            trials = [
                dict(
                    id=id_,
                    status=status,
                    setting="setting1",
                    run_id="run",
                    output=str(root / "run"),
                )
                for id_, status in [
                    ("abc12345", "finished"),
                    ("abc99999", "pending"),
                    ("def12345", "finished"),
                ]
            ]
            (root / "manifest.json").write_text(json.dumps({"trials": trials}))
            output = root / "digests"
            script = Path(__file__).resolve().parents[1] / "scripts/digest_trials.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    f"experiment={root}",
                    f"output={output}",
                    "only=[abc]",
                    "reasoning=false",
                    "result_limit=3",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            index = json.loads((output / "index.json").read_text())
            self.assertEqual([entry["id"] for entry in index], ["abc12345"])
            text = (output / "abc12345.md").read_text()
            self.assertIn("Model reasoning omitted", text)
            self.assertIn("abc\n[... 7 chars omitted ...]", text)
            self.assertNotIn("abcdefghij", text)
            self.assertFalse((root / ".hydra").exists())

    def test_invalid_limit_fails_before_creating_output(self):
        from harbor_adapter.digests import write_digests
        from harbor_adapter.experiment_config import load_config

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "digests"
            cfg = load_config(
                "digest", ["experiment=missing", f"output={output}", "result_limit=0"]
            )
            with self.assertRaisesRegex(ValueError, "positive"):
                write_digests(cfg)
            self.assertFalse(output.exists())

    def test_config_requires_paths_and_validates_types(self):
        from hydra.errors import ConfigCompositionException
        from omegaconf.errors import MissingMandatoryValue

        from harbor_adapter.experiment_config import load_config

        with self.assertRaises(MissingMandatoryValue):
            load_config("digest")
        with self.assertRaises(ConfigCompositionException):
            load_config("digest", ["reasoning=maybe"])
        with self.assertRaises(ConfigCompositionException):
            load_config("digest", ["result_limit=abc"])
