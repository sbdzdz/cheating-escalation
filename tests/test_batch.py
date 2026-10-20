import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harbor_adapter.batch import (
    add_slots,
    check_settings,
    digest,
    files_hash,
    implementation,
    import_analysis,
    locked,
    read,
    reconcile,
    save,
)


class BatchTests(unittest.TestCase):
    def test_changed_zcode_source_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pin_path = root / "configs/zcode/source.json"
            pin = {"repository": "https://example.com/zcode.git", "commit": "a" * 40}
            save(pin_path, pin)
            directory = root / "experiment"
            task = directory / "settings/s/task"
            task.mkdir(parents=True)
            (task / "task.toml").write_text('schema_version = "1.3"\n')
            profile = {"runtime": "zcode"}
            with patch("harbor_adapter.batch.ROOT", root):
                spec = {
                    "implementation": implementation(),
                    "task_files": files_hash(task.rglob("*"), task),
                    "profile": profile,
                }
                save(directory / "settings/s/setting.json", spec)
                save(
                    directory / "settings/s/model.json",
                    {"profiles": {"zcode": profile}},
                )
                manifest = {
                    "settings": {
                        "s": {
                            "fingerprint": digest(spec),
                            "task": str(task),
                            "profile": "zcode",
                        }
                    }
                }
                check_settings(directory, manifest)
                for field, value in (
                    ("commit", "b" * 40),
                    ("repository", "https://example.com/another-zcode.git"),
                ):
                    with self.subTest(field=field):
                        save(pin_path, {**pin, field: value})
                        with self.assertRaisesRegex(
                            ValueError, "Implementation/configuration changed"
                        ):
                            check_settings(directory, manifest)
                        save(pin_path, pin)
                        check_settings(directory, manifest)

    def test_target_counts_slots_not_retries(self):
        m = dict(settings={"a": {}, "old": {"historical": True}}, trials=[])
        add_slots(m, 2)
        m["trials"][0]["status"] = "infrastructure_error"
        m["trials"].append(dict(m["trials"][0], id="retry"))
        add_slots(m, 2)
        self.assertEqual(len(m["trials"]), 3)
        add_slots(m, 3)
        self.assertEqual(len(m["trials"]), 4)

    def test_receipt_wins_and_dead_worker_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            save(
                d / "receipts/a.json",
                {"status": "finished", "outcome": "budget_exhausted"},
            )
            m = {"trials": [dict(id=i, status="running", pid=123) for i in ("a", "b")]}
            with patch("harbor_adapter.batch.alive", return_value=False):
                reconcile(d, m)
            self.assertEqual(
                [t["status"] for t in m["trials"]], ["finished", "interrupted"]
            )

    def test_lock_excludes_other_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            with locked(Path(tmp)):
                with self.assertRaises(ValueError):
                    with locked(Path(tmp)):
                        pass

    def test_identity_is_order_independent(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))
        self.assertNotEqual(digest({"a": 1}), digest({"a": 2}))

    def test_import_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            row = dict(
                run_ids=["old"],
                number="15",
                bits=4,
                fermat_increments=0,
                cost_usd="0.12",
                classification={"source": "manual"},
            )
            save(d / "input.json", dict(model="m", condition="baseline", trials=[row]))
            m = import_analysis(d / "input.json", d / "experiment")
            self.assertEqual(m["trials"][0]["historical_row"], row)
            self.assertTrue(next(iter(m["settings"].values()))["historical"])
            add_slots(m, 15)
            self.assertEqual(len(m["trials"]), 1)

    def test_scheduler_limits_concurrency_and_resumes_without_duplicates(self):
        from harbor_adapter.batch import schedule

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            m = dict(settings={"s": {}}, trials=[], parallel=2)
            add_slots(m, 5)
            launched = []

            class Child:
                pid = 123

                def poll(self):
                    return 0

            def launch(command, **kwargs):
                tid = command[-1]
                launched.append(tid)
                save(
                    d / "receipts" / f"{tid}.json",
                    dict(status="finished", outcome="completed"),
                )
                return Child()

            rounds = []

            def tick(_):
                rounds.append(len(launched))

            with (
                patch("harbor_adapter.batch.check_settings"),
                patch("harbor_adapter.batch.subprocess.Popen", side_effect=launch),
                patch("harbor_adapter.batch.time.sleep", side_effect=tick),
            ):
                schedule(d, m)
                schedule(d, m)
            self.assertEqual(len(set(launched)), 5)
            self.assertEqual(len(launched), 5)
            self.assertEqual(rounds, [2, 4, 5])
