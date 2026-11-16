"""Harbor adapter for the closed tool-only experiment runner."""

import json
import shlex

from harbor.agents.installed.base import BaseInstalledAgent

from environment.runtime_image import runtime_spec


class ControlledAgent(BaseInstalledAgent):
    def __init__(
        self,
        *args,
        reasoning_effort="high",
        max_tokens=256000,
        max_turns=10000,
        request_timeout_sec=3600,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        for value in (max_tokens, max_turns, request_timeout_sec):
            if type(value) is not int or value < 1:
                raise ValueError("Runner limits must be positive integers")
        self.settings = dict(
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            max_turns=max_turns,
            request_timeout_sec=request_timeout_sec,
        )

    @staticmethod
    def name():
        return "controlled"

    async def install(self, environment):
        _, _, expected = runtime_spec("controlled")
        result = await self.exec_as_agent(
            environment, command="cat /opt/experiment-runtime.json"
        )
        if json.loads(result.stdout) != expected:
            raise ValueError("Controlled runtime does not match the pinned runner")

    async def run(self, instruction, environment, context):
        if (
            len(self.mcp_servers) != 1
            or self.mcp_servers[0].transport != "streamable-http"
        ):
            raise ValueError("Controlled runner requires the single task MCP sidecar")
        config = dict(
            self.settings,
            model=self.model_name,
            instruction=instruction,
            mcp_url=self.mcp_servers[0].url,
        )
        path = "/tmp/controlled-session.json"
        await self._upload_config_text(
            environment,
            content=json.dumps(config),
            remote_path=path,
            filename="controlled-session.json",
        )
        context.metadata = {
            "harness": "controlled-tools",
            "runner": runtime_spec("controlled")[2],
        }
        result = await self.exec_as_agent(
            environment,
            command="python /opt/controlled/controlled_runner.py --config "
            + shlex.quote(path)
            + " --log "
            + shlex.quote(str(self.environment_logs_dir) + "/model-calls.jsonl"),
        )
        if result.return_code != 0:
            raise RuntimeError(
                f"Controlled runner failed with exit code {result.return_code}: "
                + (result.stderr or result.stdout or "No error output")[-2000:]
            )
