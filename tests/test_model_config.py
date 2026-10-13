import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from harbor.agents.installed.acp import AcpAgent
from harbor.models.task.config import MCPServerConfig

from harbor_adapter.agents.deepseek import FactorizationDeepSeek, provider_patch
from harbor_adapter.model_config import DEFAULT_CONFIG, ROOT, load_profile
from harbor_adapter.outputs import compact_job


class ModelConfigTests(unittest.TestCase):
    def test_profiles_generate_harbor_jobs_without_credentials(self):
        env = {k: v for k, v in os.environ.items() if "API_KEY" not in k}
        for name, target in [
            ("kimi-k3", "KIMI_MODEL"),
            ("deepseek-v4-flash", "DEEPSEEK"),
        ]:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_factorization.py"),
                    "--profile",
                    name,
                    "--max-cost-usd",
                    "10",
                    "--print-config",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            job = json.loads(result.stdout)
            agent = job["agents"][0]
            self.assertEqual(agent["model_name"], load_profile(name=name)[1]["model"])
            self.assertEqual(agent["env"][target + "_API_KEY"], "${BUDGET_PROXY_TOKEN}")
            self.assertEqual(
                agent["env"][target + "_BASE_URL"],
                "http://host.docker.internal:PORT/v1",
            )

    def test_config_default_selects_model(self):
        config = {
            "default": "deepseek-v4-flash",
            "profiles": {
                "deepseek-v4-flash": load_profile(name="deepseek-v4-flash")[1]
            },
        }
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "models.json"
            path.write_text(json.dumps(config))
            name, profile = load_profile(path)
            self.assertEqual(name, "deepseek-v4-flash")
            self.assertIn("FactorizationDeepSeek", profile["agent"])
        with self.assertRaisesRegex(ValueError, "Unknown model profile"):
            load_profile(name="missing")

    def test_deepseek_routes_main_and_subagent_defaults(self):
        patch = {
            row["id"]: row
            for row in provider_patch("deepseek/deepseek-v4-flash", "high")
        }
        self.assertEqual(
            patch["llm-deepseek"]["config"]["protocol"], "chat-completions"
        )
        self.assertEqual(
            patch["acp"]["config"]["model"],
            patch["agent-default-model"]["config"]["model"],
        )
        self.assertTrue(patch["tool-web"]["disabled"])

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
            agent = FactorizationDeepSeek(
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
