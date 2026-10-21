import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from harbor.models.task.config import MCPServerConfig

from harbor_adapter.agents.zcode import READ_SUMMARY, ZCode, zcode_config
from harbor_adapter.outputs import compact_job


class ZCodeTests(unittest.TestCase):
    def test_summary_rejects_failed_turn_despite_final_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"type":"turn.failed"}\n{"type":"result"}\n')
            result = subprocess.run(
                [sys.executable, "-c", READ_SUMMARY, str(path)], capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            path.write_text(
                '{"type":"turn.completed"}\n{"type":"result","usage":{"inputTokens":42}}\n'
            )
            result = subprocess.run(
                [sys.executable, "-c", READ_SUMMARY, str(path)],
                capture_output=True,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout)["usage"]["inputTokens"], 42)

    def test_mcp_transports_and_model_selection(self):
        config = zcode_config(
            "z-ai/glm-5.3-flash",
            [
                MCPServerConfig(
                    name="verifier",
                    transport="streamable-http",
                    url="http://verifier:8000/mcp",
                ),
                MCPServerConfig(
                    name="local",
                    transport="stdio",
                    command="python",
                    args=["server.py"],
                ),
            ],
        )
        self.assertEqual(config["mcp"]["servers"]["verifier"]["type"], "http")
        self.assertEqual(config["mcp"]["servers"]["local"]["args"], ["server.py"])
        self.assertEqual(config["model"], "evaluation/z-ai/glm-5.3-flash")
        self.assertNotIn("apiKey", json.dumps(config))

    def test_interrupted_transcript_retains_tool_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            trial = job / "debug/trial"
            (trial / "agent").mkdir(parents=True)
            (trial / "result.json").write_text("{}")
            event = {"type": "tool.completed", "output": "factor result"}
            (trial / "agent/zcode-events.jsonl").write_text(
                json.dumps(event) + '\n{"type":'
            )
            compact_job(job)
            transcript = json.loads((job / "trials/trial/transcript.json").read_text())
            self.assertEqual(transcript["format"], "zcode-events-v1")
            self.assertEqual(transcript["events"], [event])
            self.assertEqual(transcript["unparsed_lines"], ['{"type":'])


class ZCodeInstallTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_runtime_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = ZCode(logs_dir=Path(directory), model_name="z-ai/glm-5.3-flash")
            agent.exec_as_agent = AsyncMock(return_value=SimpleNamespace(stdout="{}"))
            with self.assertRaisesRegex(ValueError, "does not match"):
                await agent.install(object())
