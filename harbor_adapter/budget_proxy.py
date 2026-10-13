"""Per-run serialized OpenRouter relay with post-request cost accounting."""

import json
import secrets
import threading
import time
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx


class Budget:
    def __init__(self, limit, path):
        self.limit = Decimal(str(limit))
        if not self.limit.is_finite() or self.limit <= 0:
            raise ValueError("Budget must be a finite positive dollar amount")
        self.path = Path(path)
        self.spent = Decimal(0)
        self.unknown = False
        self.requests = []
        self.lock = threading.Lock()
        self.save()

    @property
    def status(self):
        if self.unknown:
            return "cost_unknown"
        return "budget_exhausted" if self.spent >= self.limit else "available"

    def record(self, cost, generation_id=None, **metadata):
        try:
            value = Decimal(str(cost))
            if not value.is_finite() or value < 0:
                raise ValueError("Invalid cost")
        except (InvalidOperation, ValueError):
            value = None
        if value is None:
            self.unknown = True
        else:
            self.spent += value
        self.requests.append(
            {
                "generation_id": generation_id,
                "cost_usd": str(value) if value is not None else None,
                **metadata,
            }
        )
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "limit_usd": str(self.limit),
                    "spent_usd": str(self.spent),
                    "status": self.status,
                    "requests": self.requests,
                },
                indent=2,
            )
        )
        temporary.replace(self.path)


class BudgetProxy:
    def __init__(self, key, limit, path, *, client=None):
        self.budget = Budget(limit, path)
        self.token = secrets.token_urlsafe(32)
        self.client = client or httpx.Client(timeout=httpx.Timeout(600, connect=30))
        self.key = key
        self.stopping = False
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass  # Never log headers, prompts, or credentials.

            def error(self, status, message):
                data = json.dumps(
                    {"error": {"message": message, "type": "run_budget"}}
                ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
                self.close_connection = True

            def do_POST(self):
                if self.headers.get("Authorization") != f"Bearer {proxy.token}":
                    self.error(401, "Invalid run token")
                    return
                if self.path != "/v1/chat/completions":
                    self.error(404, "Only chat completions are supported")
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32 * 1024 * 1024:
                        raise ValueError()
                    payload = json.loads(self.rfile.read(size))
                    if not isinstance(payload, dict):
                        raise ValueError()
                except (ValueError, json.JSONDecodeError):
                    self.error(400, "Invalid request")
                    return
                # Covers the entire upstream request AND cost reconciliation.
                with proxy.budget.lock:
                    if proxy.stopping:
                        self.error(503, "Run has ended")
                        return
                    if proxy.budget.status != "available":
                        self.error(402, proxy.budget.status)
                        return
                    self.forward(payload)

            def forward(self, payload):
                cost, generation = None, None
                transport_error = None
                started = False
                downstream_alive = True

                def observe(data):
                    nonlocal cost, generation
                    if isinstance(data, dict):
                        generation = data.get("id") or generation
                        usage = data.get("usage")
                        if isinstance(usage, dict) and usage.get("cost") is not None:
                            cost = usage["cost"]

                def write(data):
                    nonlocal downstream_alive
                    if downstream_alive:
                        try:
                            self.wfile.write(data)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            downstream_alive = False
                    # Still drain upstream to obtain its final billed cost.

                try:
                    with proxy.client.stream(
                        "POST",
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {proxy.key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    ) as response:
                        self.send_response(response.status_code)
                        self.send_header(
                            "Content-Type",
                            response.headers.get("content-type", "application/json"),
                        )
                        self.send_header("Connection", "close")
                        self.end_headers()
                        started = True
                        if "text/event-stream" in response.headers.get(
                            "content-type", ""
                        ):
                            for line in response.iter_lines():
                                if line.startswith("data:"):
                                    try:
                                        observe(json.loads(line[5:].strip()))
                                    except ValueError:
                                        pass  # Includes SSE [DONE].
                                write((line + "\n").encode())
                        else:
                            data = response.read()
                            try:
                                observe(json.loads(data))
                            except ValueError:
                                pass
                            write(data)
                except Exception as exc:
                    transport_error = type(exc).__name__
                    # A failed transport can still have incurred a charge.
                    if not started:
                        self.error(502, "Upstream request failed; cost unknown")
                finally:
                    source = "stream_or_response"
                    if cost is None and generation:
                        cost = proxy.lookup_cost(generation)
                        source = (
                            "generation_lookup" if cost is not None else "unresolved"
                        )
                    proxy.budget.record(
                        cost,
                        generation,
                        cost_source=source,
                        transport_error=transport_error,
                    )
                    self.close_connection = True

        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def lookup_cost(self, generation):
        """Recover billed cost after a truncated response, while still holding the lock."""
        for attempt in range(3):
            if attempt:
                time.sleep(attempt)
            try:
                response = self.client.get(
                    "https://openrouter.ai/api/v1/generation",
                    params={"id": generation},
                    headers={"Authorization": f"Bearer {self.key}"},
                    timeout=10,
                )
                response.raise_for_status()
                value = response.json().get("data", {}).get("total_cost")
                cost = Decimal(str(value))
                if cost.is_finite() and cost >= 0:
                    return cost
            except (httpx.HTTPError, ValueError, InvalidOperation, AttributeError):
                pass
        return None

    @property
    def url(self):
        return f"http://host.docker.internal:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopping = True
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        # Reconcile any in-flight response even if the CLI exited early.
        with self.budget.lock:
            self.client.close()
