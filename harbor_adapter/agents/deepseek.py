"""DeepSeek's ACP harness with OpenRouter routing and the task's web-tool policy."""

import json
import shlex
from pathlib import Path

from harbor.agents.installed.acp import AcpAgent


def provider_patch(model, effort):
    # JSON is YAML-compatible. No credential or endpoint is written into this file:
    # the provider resolves DEEPSEEK_API_KEY and DEEPSEEK_BASE_URL at runtime.
    return [
        {
            "id": "llm-deepseek",
            "config": {
                "protocol": "chat-completions",
                "reasoningEffort": effort,
                "models": [{"id": model, "contextWindow": 1048576}],
            },
        },
        {"id": "acp", "config": {"provider": "deepseek-official", "model": model}},
        {
            "id": "agent-default-model",
            "config": {"provider": "deepseek-official", "model": model},
        },
        {"id": "tool-web", "disabled": True},
        {"id": "web-search-deepseek", "disabled": True},
    ]


class FactorizationDeepSeek(AcpAgent):
    _RUNTIME = "/tmp/factorization-dsh-runtime"

    async def exec_as_agent(self, environment, command, env=None, **kwargs):
        if env and "HARBOR_ACP_REQUESTED_MODEL" in env:
            # DSH advertises ACP model selectors as JSON [provider, model] pairs.
            env = dict(env)
            env["HARBOR_ACP_REQUESTED_MODEL"] = json.dumps(
                ["deepseek-official", env["HARBOR_ACP_REQUESTED_MODEL"]],
                separators=(",", ":"),
            )
        return await super().exec_as_agent(environment, command, env=env, **kwargs)

    async def install(self, environment):
        # The CLI's semver ranges otherwise mix incompatible prerelease plugins.
        runtime = Path(__file__).resolve().parents[2] / "configs/acp/deepseek-runtime"
        package = json.loads((runtime / "package.json").read_text())
        version = package["dependencies"]["@deepseek-ai/dsh"]
        if self._require_registry_entry().version != version:
            raise ValueError("DeepSeek registry version must match the locked runtime")
        prebuilt = self._get_env("FACTORIZATION_PREBUILT_RUNTIME")
        if prebuilt:
            from harbor_adapter.runtime_image import runtime_spec

            _, _, expected = runtime_spec(prebuilt)
            result = await self.exec_as_agent(
                environment, command="cat /opt/factorization-runtime.json"
            )
            if json.loads(result.stdout) != expected:
                raise ValueError(
                    "Prebuilt runtime does not match the current harness lock; rebuild it"
                )
            await self.exec_as_agent(
                environment,
                command=(
                    'node --version && /opt/harbor-acp-venv/bin/python -c "import acp" '
                    f"&& test -x {self._RUNTIME}/node_modules/.bin/dsh"
                ),
            )
            self._preinstalled = True
            await super().install(environment)
            return
        await self.exec_as_agent(environment, command=f"mkdir -p {self._RUNTIME}")
        for name in ("package.json", "package-lock.json"):
            await self._upload_config_text(
                environment,
                content=(runtime / name).read_text(),
                remote_path=f"{self._RUNTIME}/{name}",
                filename=name,
            )
        await super().install(environment)

    def _build_node_install_command(self):
        if getattr(self, "_preinstalled", False):
            return "true"
        return (
            super()._build_node_install_command()
            + f" && cd {self._RUNTIME} && npm ci --no-audit --no-fund"
        )

    def _build_dependencies_command(self, kind):
        if getattr(self, "_preinstalled", False):
            return "true"
        command = super()._build_dependencies_command(kind)
        # Our task image already supplies these; avoid a redundant apt download.
        # Harbor still provisions its separate Python 3.12 ACP runner below.
        marker = "if command -v apt-get >/dev/null 2>&1; then"
        guard = (
            "if command -v python3 >/dev/null 2>&1 "
            "&& command -v curl >/dev/null 2>&1 "
            "&& command -v tar >/dev/null 2>&1 "
            "&& [ -s /etc/ssl/certs/ca-certificates.crt ]; then\n"
            "  :\nelif command -v apt-get >/dev/null 2>&1; then"
        )
        if marker not in command:
            raise RuntimeError("Harbor ACP bootstrap changed; review dependency setup")
        return command.replace(marker, guard, 1)

    def _build_launcher_script(self, kind, target):
        if kind != "npx":
            raise ValueError("DeepSeek uses the locked npm runtime")
        launcher = super()._build_launcher_script(kind, target)
        invocation = "npx -y " + shlex.quote(target.package)
        return launcher.replace(invocation, f"{self._RUNTIME}/node_modules/.bin/dsh", 1)

    async def run(self, instruction, environment, context):
        patch = provider_patch(
            self.model_name, self._get_env("DSH_REASONING_EFFORT") or "high"
        )
        await self.exec_as_agent(
            environment,
            command='mkdir -p "$DSH_HOME" && printf %s '
            + shlex.quote(json.dumps(patch))
            + ' > "$DSH_HOME/cordis.patch.yml"',
        )
        await super().run(instruction, environment, context)
