import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plotting import effort


def transcript(usage):
    return {
        "format": "model-calls-v1",
        "calls": [
            {
                "index": 0,
                "response": {
                    "tool_calls": [{"id": "read"}],
                    "usage": {"total_tokens": 100},
                },
            },
            {
                "index": 1,
                "response": {
                    "tool_calls": [{"id": "cheat"}, {"id": "parallel"}],
                    "usage": usage,
                },
            },
        ],
    }


class EffortTests(unittest.TestCase):
    def test_model_calls_use_issuing_context_and_do_not_order_parallel_tools(self):
        data = transcript({"prompt_tokens": 200, "completion_tokens": 20})
        self.assertEqual(
            effort.model_call_effort(data, {"parallel"}), {"calls": 1, "tokens": 220}
        )
        self.assertEqual(
            effort.model_call_effort(transcript(None), {"cheat"}),
            {"calls": 1, "tokens": None},
        )
        with self.assertRaisesRegex(ValueError, "absent"):
            effort.model_call_effort(data, {"stale-id"})

    def test_current_and_legacy_transcripts_and_honest_trial(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(effort, "ROOT", Path(tmp)),
        ):
            run = Path(tmp) / "outputs/harbor/run"
            trial = run / "trials/trial"
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(
                json.dumps(
                    {
                        "agent_execution": {
                            "started_at": "2026-01-01T00:00:00Z",
                            "finished_at": "2026-01-01T00:02:00Z",
                        }
                    }
                )
            )
            # Honest runs need no annotation or transcript to report elapsed time.
            self.assertEqual(
                effort.deepseek_effort(
                    {"run_id": "run", "submission_method": "manual"}
                ),
                {"calls": None, "tokens": None, "minutes": 2},
            )
            row = {
                "run_id": "run",
                "submission_method": "B",
                "tool_evidence": [{"tool_call_id": "cheat"}],
            }
            (trial / "transcript.json").write_text(
                json.dumps(transcript({"total_tokens": 220}))
            )
            self.assertEqual(
                effort.deepseek_effort(row), {"calls": 1, "tokens": 220, "minutes": 2}
            )
            glm_row = dict(row, transcript=str(trial / "transcript.json"))
            self.assertEqual(
                effort.glm_effort(glm_row), {"calls": 1, "tokens": 220, "minutes": 2}
            )
            row.pop("tool_evidence")
            (run / "annotation.json").write_text(
                json.dumps({"evidence": [{"trajectory_step": 3}]})
            )
            with self.assertRaisesRegex(ValueError, "requires the original trajectory"):
                effort.deepseek_effort(row)
            (trial / "trajectory.json").write_text(
                json.dumps(
                    {
                        "steps": [
                            {"step_id": 1},
                            {"step_id": 2, "tool_calls": [{"tool_call_id": "read"}]},
                            {"step_id": 3, "tool_calls": [{"tool_call_id": "cheat"}]},
                        ]
                    }
                )
            )
            self.assertEqual(effort.deepseek_effort(row)["tokens"], 220)
            (trial / "transcript.json").write_text(
                json.dumps(
                    {
                        "format": "acp-events-v1",
                        "events": [
                            {
                                "payload": {
                                    "update": {
                                        "sessionUpdate": "usage_update",
                                        "used": 180,
                                    }
                                }
                            },
                            {"payload": {"update": {"toolCallId": "cheat"}}},
                        ],
                    }
                )
            )
            self.assertEqual(
                effort.deepseek_effort(row), {"calls": 1, "tokens": 180, "minutes": 2}
            )

    def test_figure_handles_missing_usage_and_long_runs(self):
        data = {
            model: {
                condition: [dict(calls=0, tokens=None, minutes=300, cheated=True)]
                for condition, _ in effort.CONDITIONS
            }
            for model in effort.MODELS
        }
        with patch.object(effort, "efforts", return_value=data):
            fig = effort.figure("paper", "deepseek")
            try:
                self.assertGreater(fig.axes[0].get_xlim()[1], 0)
                self.assertGreater(fig.axes[1].get_xlim()[1], 0)
                self.assertGreaterEqual(fig.axes[2].get_xlim()[1], 300)
            finally:
                effort.plt.close(fig)
