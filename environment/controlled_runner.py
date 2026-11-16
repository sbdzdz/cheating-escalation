"""Minimal chat-completions loop: only the fixed task MCP operations can execute."""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

try:
    from model_log import ModelLog, Response
except ModuleNotFoundError:
    from environment.model_log import ModelLog, Response


def advertised_tools(tools, instruction=None):
    names = {tool.name for tool in tools}
    expected = {"read_instance", "read_notes", "write_notes", "R1", "R2"}
    verifiers = names & {"verify_factors", "verify_subset"}
    base = {"read_instance", "read_notes", "write_notes"} | verifiers
    shortcuts = names - base
    opaque = len(shortcuts) == 3 and all(
        re.fullmatch(r"[a-f][0-9a-f]{5}", n) for n in shortcuts
    )
    if len(verifiers) != 1 or (not opaque and names != expected | verifiers):
        raise ValueError("Unexpected controlled tool catalog")
    if opaque:
        if any(t.description for t in tools if t.name in shortcuts):
            raise ValueError("Opaque shortcuts must not have descriptions")
        if instruction is None:
            raise ValueError("Opaque tools require the saved prompt order")
        catalog = instruction.split("Available operations:\n", 1)[1].split(
            "\n\nPermitted operations:", 1
        )[0]
        order = [line[2:].split(":", 1)[0] for line in catalog.splitlines()]
        if len(order) != len(names) or set(order) != names:
            raise ValueError("Prompt and tool catalog disagree")
        tools = sorted(tools, key=lambda t: order.index(t.name))
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                **({"description": t.description} if t.description else {}),
                "parameters": t.inputSchema,
            },
        }
        for t in tools
    ]


async def run(config, log_path, *, base_url=None, api_key=None):
    # No model-supplied path, URL, command, import or code is ever evaluated.
    messages = [{"role": "user", "content": config["instruction"]}]
    log = ModelLog(log_path)
    async with streamablehttp_client(config["mcp_url"]) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = advertised_tools(
                (await session.list_tools()).tools, config["instruction"]
            )
            allowed = {t["function"]["name"] for t in tools}
            async with httpx.AsyncClient(
                timeout=config["request_timeout_sec"]
            ) as client:
                for _ in range(config["max_turns"]):
                    payload = dict(
                        model=config["model"],
                        messages=messages,
                        tools=tools,
                        max_tokens=config["max_tokens"],
                        stream=False,
                        reasoning={"effort": config["reasoning_effort"]},
                    )
                    response = await client.post(
                        (base_url or os.environ["CONTROLLED_BASE_URL"]).rstrip("/")
                        + "/chat/completions",
                        headers={
                            "Authorization": "Bearer "
                            + (api_key or os.environ["CONTROLLED_API_KEY"])
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    body = response.json()
                    parsed = Response()
                    parsed.add(body)
                    log.record(payload, parsed, status=response.status_code)
                    choice = body["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise RuntimeError(
                            "Controlled runner output-token limit reached"
                        )
                    if choice.get("finish_reason") not in {"stop", "tool_calls"}:
                        raise RuntimeError(
                            "Unexpected model finish reason: "
                            + str(choice.get("finish_reason"))
                        )
                    message = choice["message"]
                    messages.append(
                        {
                            k: v
                            for k, v in message.items()
                            if k
                            in {
                                "role",
                                "content",
                                "tool_calls",
                                "reasoning_details",
                                "reasoning_content",
                            }
                        }
                    )
                    calls = message.get("tool_calls") or []
                    if not calls:
                        if choice["finish_reason"] != "stop" or not message.get(
                            "content"
                        ):
                            raise RuntimeError(
                                "Model ended without a final answer or tool call"
                            )
                        return
                    for call in calls:
                        name = call["function"]["name"]
                        try:
                            if name not in allowed:
                                raise ValueError(
                                    "Unknown operation; no execution occurred"
                                )
                            raw_arguments = call["function"].get("arguments", "")
                            try:
                                arguments = json.loads(raw_arguments)
                            except (ValueError, TypeError):
                                arguments = {
                                    "__invalid_json_arguments__": raw_arguments
                                }
                            if not isinstance(arguments, dict):
                                arguments = {"__invalid_argument_value__": arguments}
                            result = await session.call_tool(name, arguments)
                            content = result.model_dump_json()
                        except (ValueError, TypeError, KeyError) as exc:
                            content = json.dumps({"isError": True, "error": str(exc)})
                        messages.append(
                            dict(role="tool", tool_call_id=call["id"], content=content)
                        )
    raise RuntimeError("Controlled runner turn limit reached")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()
    asyncio.run(run(json.loads(Path(args.config).read_text()), args.log))
