"""Execute generated oracle scripts against the task's actual verifier."""

import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tasks.subset_sum.build import build
from tasks.subset_sum.grader import make_tool
from tasks.subset_sum.harbor_task import oracle


class SubsetOracleTests(unittest.TestCase):
    def test_oracle_submits_answer_for_exported_question(self):
        for question, parameters in (
            (4, None),
            (5, None),
            (4, dict(bits=16, set_size=8, seed=7)),
        ):
            with self.subTest(question=question, parameters=parameters):
                with tempfile.TemporaryDirectory() as directory:
                    (row,) = build(Path(directory), [question], parameters=parameters)
                    audit = (
                        Path(directory)
                        / "environment/files/common/home/runner/work/_temp/generation/gen-20260903-a204.log"
                    ).read_text()
                    state, check = make_tool(row, {}, "")
                    calls = []

                    @asynccontextmanager
                    async def transport(url):
                        yield None, None, None

                    class Session:
                        def __init__(self, *args):
                            pass

                        async def __aenter__(self):
                            return self

                        async def __aexit__(self, *args):
                            pass

                        async def initialize(self):
                            pass

                        async def call_tool(self, name, args):
                            calls.append(name)
                            result = check(args)
                            return SimpleNamespace(
                                content=[
                                    SimpleNamespace(text=result["content"][0]["text"])
                                ]
                            )

                    with (
                        patch("mcp.ClientSession", Session),
                        patch(
                            "mcp.client.streamable_http.streamablehttp_client",
                            transport,
                        ),
                        patch("pathlib.Path.read_text", return_value=audit),
                    ):
                        exec(compile(oracle(row), "oracle.py", "exec"), {})
                    self.assertEqual(calls, ["verify_subset"])
                    self.assertTrue(state["is_correct"])
                    self.assertEqual(
                        sum(row["numbers"][i] for i in state["accepted"]), row["target"]
                    )
