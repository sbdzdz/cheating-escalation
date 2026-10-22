"""Run the pinned Z.ai CLI inside Harbor's task environment."""

import json
import shlex

from harbor.agents.installed.base import BaseInstalledAgent

from environment.runtime_image import runtime_spec

READ_SUMMARY = """
import json, sys
summary, outcome = None, None
with open(sys.argv[1]) as stream:
    for line in stream:
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get('type') in ('turn.completed', 'turn.failed'):
            outcome = event['type']
        if event.get('type') == 'result':
            summary = event
if summary is None or outcome == 'turn.failed':
    raise RuntimeError('ZCode did not complete successfully; inspect zcode-events.jsonl')
print(json.dumps({'usage': summary.get('usage', {}), 'session_id': summary.get('sessionId')}))
"""


def zcode_config(model, servers):
    """Credentials are inserted only inside the container, never in host logs."""
    mcp = {}
    for server in servers:
        if server.transport == "stdio":
            mcp[server.name] = {
                "type": "stdio",
                "command": server.command,
                "args": server.args,
            }
        else:
            mcp[server.name] = {
                "type": "http" if server.transport == "streamable-http" else "sse",
                "url": server.url,
            }
    return {
        "model": f"evaluation/{model}",
        "provider": {
            "evaluation": {
                "kind": "openai-compatible",
                "models": {model: {"contextWindow": 1048576}},
            }
        },
        "plugins": {"enabled": False},
        "mcp": {"servers": mcp},
    }


class ZCode(BaseInstalledAgent):
    @staticmethod
    def name():
        return "zcode"

    def get_version_command(self):
        return "node /opt/zcode/zcode.cjs --version"

    async def install(self, environment):
        _, _, expected = runtime_spec("zcode")
        result = await self.exec_as_agent(
            environment, command="cat /opt/experiment-runtime.json"
        )
        if json.loads(result.stdout) != expected:
            raise ValueError("ZCode runtime does not match the source pin; rebuild it")
        await self.exec_as_agent(environment, command=self.get_version_command())

    async def run(self, instruction, environment, context):
        if not self.model_name:
            raise ValueError("ZCode requires a model identifier")
        config = zcode_config(self.model_name, self.mcp_servers)
        # ZCode imports its CLI provider configuration into its personal provider
        # store. Keep both stores outside /logs so credentials are never archived.
        setup = (
            "import json, os\nfrom pathlib import Path\n"
            f"config = json.loads({json.dumps(config)!r})\n"
            "config['provider']['evaluation']['options'] = {"
            "'apiKey': os.environ['ZCODE_API_KEY'], "
            "'baseURL': os.environ['ZCODE_BASE_URL']}\n"
            "path = Path.home() / '.zcode/cli/config.json'\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "os.umask(0o077)\n"
            "path.write_text(json.dumps(config))\n"
        )
        await self.exec_as_agent(
            environment, command="python3 -c " + shlex.quote(setup)
        )
        logs = str(self.environment_logs_dir)
        context.metadata = {"harness": "zcode", "source": runtime_spec("zcode")[2]}
        await self.exec_as_agent(
            environment,
            command=(
                "node /opt/zcode/zcode.cjs --mode yolo --locale en-US "
                "--output-format stream-json --disallowed-tools WebSearch,WebFetch "
                "--prompt "
                + shlex.quote(self.render_instruction(instruction))
                + " > "
                + shlex.quote(logs + "/zcode-events.jsonl")
                + " 2> "
                + shlex.quote(logs + "/zcode-stderr.log")
            ),
        )
        result = await self.exec_as_agent(
            environment,
            command="python3 -c "
            + shlex.quote(READ_SUMMARY)
            + " "
            + shlex.quote(logs + "/zcode-events.jsonl"),
        )
        summary = json.loads(result.stdout)
        usage = summary["usage"]
        context.n_input_tokens = usage.get("inputTokens")
        context.n_output_tokens = usage.get("outputTokens")
        context.n_cache_tokens = usage.get("cacheReadTokens")
        context.metadata["session_id"] = summary["session_id"]
