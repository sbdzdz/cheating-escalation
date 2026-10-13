"""Harbor Kimi Code with CheatBench's native web-tool policy."""

import shlex
from pathlib import Path

from harbor.agents.installed.kimi_code import KimiCode
from harbor.models.trial.paths import EnvironmentPaths

TOOL_POLICY = '[tools]\ndisabled = ["FetchURL", "WebSearch"]\n'


class FactorizationKimiCode(KimiCode):
    async def run(self, instruction, environment, context):
        try:
            await super().run(instruction, environment, context)
        finally:
            # Convert inside the container before Harbor collects agent logs.
            converter = (Path(__file__).resolve().parents[1] / "transcript.py").read_text()
            await self.exec_as_agent(
                environment,
                command="python3 -c "
                + shlex.quote(converter)
                + " "
                + shlex.quote(str(EnvironmentPaths.agent_dir / "kimi-code.txt")),
            )

    async def _configure_mcp_servers(self, environment, env):
        await super()._configure_mcp_servers(environment, env)
        await self.exec_as_agent(
            environment,
            command='mkdir -p "$KIMI_CODE_HOME" && printf %s '
            + shlex.quote(TOOL_POLICY)
            + ' > "$KIMI_CODE_HOME/config.toml"',
            env=env,
        )
