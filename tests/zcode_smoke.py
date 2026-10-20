"""Offline container smoke test: real ZCode, mock model and MCP, no API key.

Run with: uv run python tests/zcode_smoke.py
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def container_test():
    requests, verifier_calls = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_error(405)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/mcp":
                method = body.get("method")
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "smoke", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "verify_factors", "description": "Verify factors",
                                        "inputSchema": {"type": "object", "properties": {}}}]}
                elif method == "tools/call":
                    verifier_calls.append(body)
                    result = {"content": [{"type": "text", "text": "verifier-smoke-ok"}]}
                else:
                    result = {}
                self.reply({"jsonrpc": "2.0", "id": body["id"], "result": result})
                return
            assert self.path == "/v1/chat/completions", self.path
            requests.append(body)
            tools = {t["function"]["name"] for t in body.get("tools", [])}
            assert "WebSearch" not in tools and "WebFetch" not in tools, tools
            if len(requests) == 1:
                tool = "Bash"
                args = {"command": "printf zcode-smoke-ok", "description": "Smoke test"}
            elif len(requests) == 2:
                tool = next(t for t in tools if t.endswith("verify_factors"))
                args = {}
            else:
                tool = None
            delta = {"role": "assistant", "content": "smoke complete" if not tool else ""}
            if tool:
                delta["tool_calls"] = [{"index": 0, "id": f"call-{len(requests)}", "type": "function",
                                        "function": {"name": tool, "arguments": json.dumps(args)}}]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for change, finish in [(delta, None), ({}, "tool_calls" if tool else "stop")]:
                event = {"id": f"mock-{len(requests)}", "object": "chat.completion.chunk",
                         "model": body["model"], "choices": [{"index": 0, "delta": change, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

        def reply(self, data):
            raw = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    config = json.loads(Path("/smoke/config.json").read_text())
    config["provider"]["evaluation"]["options"] = {"apiKey": "mock-only", "baseURL": base + "/v1"}
    config["mcp"]["servers"]["verifier"]["url"] = base + "/mcp"
    config_path = Path.home() / ".zcode/cli/config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config))
    env = dict(os.environ,
               ZCODE_BUILTIN_PROVIDER_CONFIG_FILE="/opt/zcode/provider/zcode-builtin.json",
               ZCODE_PERSONAL_PROVIDER_CONFIG_FILE=str(Path.home() / ".zcode/v2/provider_config.json"))
    result = subprocess.run([
        "node", "/opt/zcode/zcode.cjs", "--mode", "yolo", "--locale", "en-US",
        "--output-format", "stream-json", "--disallowed-tools", "WebSearch,WebFetch",
        "--prompt", "Run the shell smoke check, call the verifier, then finish.",
    ], env=env, capture_output=True, text=True, timeout=120, cwd="/tmp")
    if result.returncode:
        raise AssertionError(result.stderr + result.stdout)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert len(requests) == 3, (len(requests), result.stdout, result.stderr)
    assert all(r["model"] == "z-ai/glm-5.3-flash" for r in requests)
    assert verifier_calls, result.stdout
    assert events[-1]["type"] == "result", events[-1]
    assert "zcode-smoke-ok" in json.dumps(requests[1]), requests[1]
    assert "verifier-smoke-ok" in json.dumps(requests[2]), requests[2]
    assert "zcode-smoke-ok" in result.stdout and "verifier-smoke-ok" in result.stdout
    assert "mock-only" not in result.stdout + result.stderr
    print("PASS: ZCode model routing, shell tools, MCP verifier, and structured transcript (no paid calls)")


if __name__ == "__main__":
    if "--container" in sys.argv:
        container_test()
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from harbor.models.task.config import MCPServerConfig
        from harbor_adapter.agents.zcode import zcode_config
        from harbor_adapter.runtime_image import runtime_spec

        with tempfile.TemporaryDirectory(prefix="zcode-smoke-") as directory:
            path = Path(directory)
            path.chmod(0o755)
            (path / "smoke.py").write_text(Path(__file__).read_text())
            (path / "config.json").write_text(json.dumps(zcode_config(
                "z-ai/glm-5.3-flash", [MCPServerConfig(name="verifier", transport="http", url="http://unused/mcp")]
            )))
            subprocess.run([
                "docker", "run", "--rm", "--network", "none", "--user", "agent",
                "--mount", f"type=bind,src={directory},dst=/smoke,readonly",
                runtime_spec("zcode")[0], "python3", "/smoke/smoke.py", "--container",
            ], check=True)
