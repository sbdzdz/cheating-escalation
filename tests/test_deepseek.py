import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from harbor.agents.installed.acp import AcpAgent
from harbor.models.task.config import MCPServerConfig

from harbor_adapter.agents.deepseek import DeepSeekAgent
from harbor_adapter.model_config import ROOT, load_profile
from harbor_adapter.outputs import compact_job


class EvidenceTests(unittest.TestCase):
    def test_acp_evidence_survives_compaction(self):
        with tempfile.TemporaryDirectory() as d:
            job = Path(d)
            agent = job / "debug/trial/agent"
            agent.mkdir(parents=True)
            (agent.parent / "result.json").write_text("{}")
            event = {"event_type": "session_update", "payload": {"text": "hello"}}
            (agent / "acp-events.jsonl").write_text(json.dumps(event) + "\n")
            (agent / "trajectory.json").write_text('{"steps":[]}')
            compact_job(job)
            result = json.loads((job / "trials/trial/transcript.json").read_text())
            self.assertEqual(result["events"], [event])
            self.assertTrue((job / "trials/trial/trajectory.json").exists())
            self.assertTrue((job / ".debug/debug.zip").exists())


class DeepSeekAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_acp_selector_verifier_and_locked_launcher(self):
        _, profile = load_profile(name="deepseek-v4-flash")
        with tempfile.TemporaryDirectory() as directory:
            agent = DeepSeekAgent(
                logs_dir=Path(directory),
                model_name=profile["model"],
                **profile["kwargs"],
                mcp_servers=[
                    MCPServerConfig(
                        name="verifier",
                        transport="streamable-http",
                        url="http://verifier:8000/mcp",
                    )
                ],
            )
            self.assertEqual(
                agent._build_mcp_servers_payload()[0]["url"], "http://verifier:8000/mcp"
            )
            with patch.object(
                AcpAgent, "exec_as_agent", new_callable=AsyncMock
            ) as execute:
                await agent.exec_as_agent(
                    object(),
                    "run",
                    env={"HARBOR_ACP_REQUESTED_MODEL": profile["model"]},
                )
                selector = execute.call_args.kwargs["env"]["HARBOR_ACP_REQUESTED_MODEL"]
                self.assertEqual(
                    json.loads(selector), ["deepseek-official", profile["model"]]
                )
            entry = agent._require_registry_entry()
            launcher = agent._build_launcher_script("npx", entry.distribution.npx)
            self.assertNotIn("npx -y", launcher)
            self.assertIn("/node_modules/.bin/dsh --profile acp", launcher)
            self.assertIn("npm ci", agent._build_node_install_command())
            lock = json.loads(
                (ROOT / "configs/acp/deepseek-runtime/package-lock.json").read_text()
            )
            self.assertEqual(
                lock["packages"]["node_modules/@deepseek-ai/dsh"]["version"],
                entry.version,
            )
