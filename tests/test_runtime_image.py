import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from harbor.agents.installed.acp import AcpAgent

from environment.agents.deepseek import DeepSeekAgent
from environment.export import export_tasks
from environment.model_config import load_profile
from environment.runtime_image import prepare_task, runtime_spec


class RuntimeImageTests(unittest.TestCase):
    def test_prepared_task_preserves_all_fixtures_and_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            (source,) = export_tasks("factorization", Path(directory) / "export")
            task = prepare_task(source, "deepseek", Path(directory))
            self.assertEqual(task, prepare_task(source, "deepseek", Path(directory)))
            for path in source.rglob("*"):
                if (
                    path.is_file()
                    and path.relative_to(source).as_posix() != "environment/Dockerfile"
                ):
                    self.assertEqual(
                        path.read_bytes(),
                        (task / path.relative_to(source)).read_bytes(),
                    )
            dockerfile = (task / "environment/Dockerfile").read_text()
            self.assertTrue(dockerfile.startswith("FROM cheating-escalation/deepseek:"))
            self.assertNotIn("npm ci", dockerfile)
            self.assertNotIn("apt-get", dockerfile)

    def test_build_context_has_only_allowlisted_inputs(self):
        image, files, metadata = runtime_spec("deepseek")
        self.assertEqual(
            set(files),
            {"Dockerfile", "package.json", "package-lock.json", "runtime.json"},
        )
        self.assertTrue(image.endswith(metadata["fingerprint"][:16]))
        self.assertNotIn("COPY . ", files["Dockerfile"].decode())


class PreinstalledAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_preinstalled_runtime_skips_downloads_and_rejects_stale_image(self):
        _, profile = load_profile(name="deepseek-v4-flash")
        _, _, metadata = runtime_spec("deepseek")
        with tempfile.TemporaryDirectory() as directory:
            agent = DeepSeekAgent(
                logs_dir=Path(directory),
                model_name=profile["model"],
                extra_env={"EXPERIMENT_PREBUILT_RUNTIME": "deepseek"},
                **profile["kwargs"],
            )
            agent.exec_as_agent = AsyncMock(
                return_value=SimpleNamespace(stdout=json.dumps(metadata))
            )
            with patch.object(AcpAgent, "install", new_callable=AsyncMock) as install:
                await agent.install(object())
                install.assert_awaited_once()
            self.assertEqual(agent._build_dependencies_command("npx"), "true")
            self.assertEqual(agent._build_node_install_command(), "true")
            agent.exec_as_agent.return_value.stdout = "{}"
            with self.assertRaisesRegex(ValueError, "does not match"):
                await agent.install(object())
