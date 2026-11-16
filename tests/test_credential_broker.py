"""Credential isolation and trial restrictions at the broker boundary."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from environment.budget_proxy import BudgetProxy
from environment.credential_broker import Broker, keychain_secret


class BrokerTests(unittest.TestCase):
    def test_keychain_failure_has_no_environment_fallback_or_secret_output(self):
        with patch("environment.credential_broker.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = "do-not-disclose"
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "inherited"}):
                with self.assertRaisesRegex(
                    RuntimeError, "^Keychain credential unavailable"
                ):
                    keychain_secret(
                        dict(keychain_service="test", keychain_account="user")
                    )
            self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_scoped_tokens_costs_revocation_and_no_key_in_worker_response(self):
        calls = []

        def upstream(request):
            self.assertEqual(request.headers["Authorization"], "Bearer upstream-secret")
            calls.append(1)
            return httpx.Response(200, json={"usage": {"cost": 0.12}})

        def factory(*args, **kwargs):
            return BudgetProxy(
                *args,
                **kwargs,
                client=httpx.Client(transport=httpx.MockTransport(upstream)),
            )

        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(
                models=["allowed"],
                max_trial_cost_usd=1,
                output_root=tmp,
                trial_lifetime_sec=60,
                request_timeout_sec=5,
            )
            broker = Broker(cfg, "upstream-secret", factory)
            req = dict(
                action="open",
                run_id="trial",
                model="allowed",
                limit="0.1",
                ledger=str(Path(tmp) / "trial/budget.json"),
            )
            for bad in [
                dict(req, model="other"),
                dict(req, limit="2"),
                dict(req, ledger=str(Path(tmp) / "wrong.json")),
            ]:
                with self.assertRaises(ValueError):
                    broker.dispatch(bad)
            reply = broker.dispatch(req)
            self.assertNotIn("upstream-secret", json.dumps(reply))
            proxy = broker.proxies["trial"]
            url = f"http://127.0.0.1:{proxy.server.server_port}/v1/chat/completions"

            def post(token, model):
                return httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"model": model},
                    trust_env=False,
                ).status_code

            try:
                self.assertEqual(post("wrong", "allowed"), 401)
                self.assertEqual(post(reply["token"], "other"), 403)
                self.assertEqual(post(reply["token"], "allowed"), 200)
                self.assertEqual(post(reply["token"], "allowed"), 402)
                self.assertEqual(len(calls), 1)
                with self.assertRaises(ValueError):
                    broker.dispatch(req)
                with self.assertRaises(ValueError):
                    broker.dispatch(dict(action="close", run_id="trial", token="wrong"))
                proxy.expires_at = time.time() - 1
                self.assertEqual(post(reply["token"], "allowed"), 403)
                broker.dispatch(
                    dict(action="close", run_id="trial", token=reply["token"])
                )
                self.assertFalse(broker.proxies)
                self.assertNotIn("upstream-secret", Path(req["ledger"]).read_text())
            finally:
                broker.close_expired(all_runs=True)


class CredentialFallbackTests(unittest.TestCase):
    def test_direct_profiles_reject_inline_credentials(self):
        from environment.model_config import normalize_profile

        base = dict(
            agent="agent",
            model="model",
            kwargs={},
            env={},
            api_key_env="OPENROUTER_API_KEY",
            key_target="CONTROLLED_API_KEY",
            url_target="CONTROLLED_BASE_URL",
        )
        for changes in [
            {"env": {"OPENROUTER_API_KEY": "synthetic"}},
            {"env": {"Authorization": "synthetic"}},
            {"kwargs": {"api_key": "synthetic"}},
            {"kwargs": {"headers": {"Authorization": "synthetic"}}},
        ]:
            with self.assertRaises(ValueError):
                normalize_profile(dict(base, **changes))
        self.assertEqual(
            normalize_profile(dict(base, kwargs={"max_tokens": 100}))["kwargs"][
                "max_tokens"
            ],
            100,
        )
