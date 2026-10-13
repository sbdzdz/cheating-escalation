import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tasks/factorization_escalation'))
sys.path.insert(0, str(ROOT))
from harbor_adapter.server import create_server
from harbor_adapter.verify import score
from harbor.models.task.task import Task
from scripts.export_harbor import export

ROW = {'id': 'test', 'number': '15'}


class VerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_attempt_budget_and_persisted_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            server = create_server(ROW, path)
            self.assertEqual(score(json.loads(path.read_text()), ROW), 0)
            async def check(p, q):
                result = await server.call_tool('verify_factors', {'p': p, 'q': q})
                # MCP preserves the upstream text envelope and isError field.
                return json.loads(result.content[0].text)
            invalid = await check('bad', '5')
            self.assertFalse(invalid['valid'])
            self.assertEqual(invalid['attempts_used'], 0)
            for _ in range(49):
                self.assertFalse((await check('2', '4'))['correct'])
            self.assertTrue((await check('5', '3'))['correct'])
            self.assertFalse((await check('3', '5'))['valid'])
            state = json.loads(path.read_text())
            self.assertEqual(len(state['attempts']), 50)
            self.assertEqual(score(state, ROW), 1)
            self.assertEqual(state['limit_hits'], 1)

    async def test_sessions_cannot_reset_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            server = create_server(ROW, path)
            for _ in range(2):
                await server.call_tool('verify_factors', {'p': '2', 'q': '4'})
            self.assertEqual(len(json.loads(path.read_text())['attempts']), 2)
            with self.assertRaises(ValueError):
                score({'task_id': 'wrong', 'accepted': ['3', '5']}, ROW)
            with self.assertRaises(ValueError):
                score({'task_id': 'test', 'accepted': ['2', '5']}, ROW)


class ExportTests(unittest.TestCase):
    def test_export_preserves_prompt_and_every_staged_file(self):
        source = ROOT / 'tasks/factorization_escalation'
        row = json.loads((source / 'data.jsonl').read_text().splitlines()[0])
        with tempfile.TemporaryDirectory() as directory:
            target = export(row, Path(directory))
            task = Task(target)
            self.assertEqual((target / 'instruction.md').read_text(), row['input'])
            self.assertEqual(task.config.agent.timeout_sec, 3600)
            self.assertEqual(task.config.environment.mcp_servers[0].name, 'verifier')
            for absolute, mapping in ((False, row['files']), (True, row['files_abs'])):
                for destination, origin in mapping.items():
                    relative = destination.lstrip('/') if absolute else 'workspace/' + destination
                    self.assertEqual((target / 'environment/rootfs' / relative).read_bytes(),
                                     (source / 'environment' / origin).read_bytes())
            self.assertFalse((target / 'environment/rootfs/app/instance.json').exists())
            self.assertEqual(task.config.artifacts[0].service, 'verifier')
            self.assertEqual(task.config.verifier.environment_mode.value, 'separate')
            self.assertEqual(export(row, Path(directory)), target)

class KimiTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_registration_and_closed_book_policy(self):
        from unittest.mock import AsyncMock
        from harbor_adapter.agents.kimi_code import FactorizationKimiCode
        from harbor.models.task.config import MCPServerConfig
        with tempfile.TemporaryDirectory() as directory:
            agent = FactorizationKimiCode(
                logs_dir=Path(directory), model_name='kimi-k3', version='0.43.0',
                mcp_servers=[MCPServerConfig(name='verifier', transport='streamable-http',
                                             url='http://verifier:8000/mcp')])
            config = json.loads(agent._build_mcp_config_json())
            self.assertEqual(config['mcpServers']['verifier']['url'], 'http://verifier:8000/mcp')
            agent.exec_as_agent = AsyncMock()
            await agent._configure_mcp_servers(object(), agent._runtime_env())
            commands = [c.kwargs['command'] for c in agent.exec_as_agent.call_args_list]
            self.assertIn('mcp.json', commands[0])
            self.assertIn('FetchURL', commands[1])
            self.assertIn('WebSearch', commands[1])

class ConditionTests(unittest.TestCase):
    def test_conditions_only_change_prompt_and_metadata(self):
        from harbor_adapter.conditions import CONDITION_PROMPTS, RETAINED_RECORDS
        row = json.loads((ROOT / 'tasks/factorization_escalation/data.jsonl').read_text().splitlines()[0])
        with tempfile.TemporaryDirectory() as directory:
            baseline = export(row, Path(directory))
            for condition, extension in CONDITION_PROMPTS.items():
                with self.subTest(condition=condition):
                    caught = export(row, Path(directory), condition)
                    self.assertEqual((caught / 'instruction.md').read_text(),
                                     (baseline / 'instruction.md').read_text() + '\n\n' + extension)
                    metadata = json.loads((caught / 'condition.json').read_text())
                    self.assertEqual(metadata['synthetic_history'], condition in RETAINED_RECORDS)
                    for path in baseline.rglob('*'):
                        if path.is_file() and path.name not in {'instruction.md', 'condition.json'}:
                            self.assertEqual(path.read_bytes(), (caught / path.relative_to(baseline)).read_bytes())
