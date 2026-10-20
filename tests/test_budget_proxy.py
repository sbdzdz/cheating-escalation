import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import httpx

from harbor_adapter.budget_proxy import BudgetProxy


class BudgetProxyTests(unittest.TestCase):
    def test_truncated_stream_cost_recovered_before_next_request(self):
        methods = []

        def upstream(request):
            methods.append(request.method)
            if request.method == "GET":
                self.assertEqual(request.url.params["id"], "gen-truncated")
                return httpx.Response(200, json={"data": {"total_cost": 0.12}})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content='data: {"id":"gen-truncated","choices":[]}\n\n',
            )

        with tempfile.TemporaryDirectory() as directory:
            with BudgetProxy(
                "key",
                "0.10",
                Path(directory) / "budget.json",
                client=httpx.Client(transport=httpx.MockTransport(upstream)),
            ) as proxy:
                self.assertEqual(self.request(proxy).status_code, 200)
                self.assertEqual(self.request(proxy).status_code, 402)
                self.assertEqual(proxy.budget.spent, Decimal("0.12"))
                self.assertEqual(
                    proxy.budget.requests[0]["cost_source"], "generation_lookup"
                )
                self.assertEqual(methods, ["POST", "GET"])

    def request(self, proxy, token=None):
        return httpx.post(
            f"http://127.0.0.1:{proxy.server.server_port}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token or proxy.token}"},
            json={"model": "test", "stream": True},
            timeout=5,
            trust_env=False,
        )

    def test_serialized_streaming_cap(self):
        calls = []

        def upstream(request):
            self.assertEqual(request.headers["Authorization"], "Bearer real-key")
            calls.append(1)
            time.sleep(0.03)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content='data: {"id":"gen-1","usage":{"cost":0.12}}\n\ndata: [DONE]\n\n',
            )

        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "budget.json"
            with BudgetProxy(
                "real-key",
                "0.10",
                ledger,
                client=httpx.Client(transport=httpx.MockTransport(upstream)),
            ) as proxy:
                with ThreadPoolExecutor(2) as pool:
                    responses = list(pool.map(lambda _: self.request(proxy), range(2)))
                self.assertEqual(sorted(r.status_code for r in responses), [200, 402])
                self.assertEqual(len(calls), 1)
                self.assertEqual(proxy.budget.status, "budget_exhausted")
            recorded = json.loads(ledger.read_text())
            self.assertEqual(recorded["spent_usd"], "0.12")
            self.assertEqual(len(recorded["requests"]), 1)
            self.assertNotIn("real-key", ledger.read_text())

    def test_missing_cost_blocks_next_call(self):
        with tempfile.TemporaryDirectory() as directory:
            client = httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={"id": "missing"})
                )
            )
            with BudgetProxy(
                "key", 2, Path(directory) / "budget.json", client=client
            ) as proxy:
                self.assertEqual(self.request(proxy).status_code, 200)
                self.assertEqual(self.request(proxy).status_code, 402)
                self.assertEqual(proxy.budget.status, "cost_unknown")

    def test_json_zero_cost_and_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            client = httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={"usage": {"cost": 0}})
                )
            )
            with BudgetProxy(
                "key", 2, Path(directory) / "budget.json", client=client
            ) as proxy:
                self.assertEqual(self.request(proxy, "wrong").status_code, 401)
                self.assertEqual(len(proxy.budget.requests), 0)
                self.assertEqual(self.request(proxy).status_code, 200)
                self.assertEqual(self.request(proxy).status_code, 200)
                self.assertEqual(proxy.budget.status, "available")

    def test_model_calls_logged_without_credentials(self):
        chunks = [
            {"id": "gen-1", "model": "m", "choices": [{"index": 0, "delta": {"reasoning": "Think "}}]},
            {"id": "gen-1", "choices": [{"index": 0, "delta": {"reasoning": "more."}}]},
            {"id": "gen-1", "choices": [{"index": 0, "delta": {"content": "Reading."}}]},
            {"id": "gen-1", "choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {"name": "read", "arguments": '{"path":'}}]}}]},
            {"id": "gen-1", "choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": ' "a.txt"}'}}]}, "finish_reason": "tool_calls"}],
             "usage": {"cost": 0.01, "completion_tokens": 9}},
        ]
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

        def upstream(request):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

        system = {"role": "system", "content": "sys"}
        user = {"role": "user", "content": "task"}
        assistant = {"role": "assistant", "content": "Reading.", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "read", "arguments": '{"path": "a.txt"}'}}]}
        tool = {"role": "tool", "tool_call_id": "call_1", "content": "file text"}
        tools = [{"type": "function", "function": {"name": "read"}}]
        with tempfile.TemporaryDirectory() as directory:
            with BudgetProxy(
                "real-key", "1", Path(directory) / "budget.json",
                client=httpx.Client(transport=httpx.MockTransport(upstream)),
            ) as proxy:
                for messages in ([system, user], [system, user, assistant, tool], [{"role": "user", "content": "title?"}]):
                    httpx.post(
                        f"http://127.0.0.1:{proxy.server.server_port}/v1/chat/completions",
                        headers={"Authorization": f"Bearer {proxy.token}"},
                        json={"model": "m", "stream": True, "messages": messages, "tools": tools},
                        timeout=5, trust_env=False,
                    )
            text = (Path(directory) / "model-calls.jsonl").read_text()
            self.assertNotIn("real-key", text)
            self.assertNotIn(proxy.token, text)
            from harbor_adapter.model_log import read

            log = read(Path(directory) / "model-calls.jsonl")
            self.assertEqual(len(log["tools"]), 1)
            first, second, side = log["calls"]
            self.assertEqual(first["new_messages"], [system, user])
            self.assertEqual(first["response"]["reasoning"], "Think more.")
            self.assertEqual(first["response"]["content"], "Reading.")
            self.assertEqual(first["response"]["tool_calls"],
                             [{"id": "call_1", "name": "read", "arguments": '{"path": "a.txt"}'}])
            self.assertEqual(first["cost_usd"], "0.01")
            self.assertEqual((second["parent"], second["new_messages"]), (0, [assistant, tool]))
            self.assertEqual((side["parent"], side["message_count"]), (None, 1))
