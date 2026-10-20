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
