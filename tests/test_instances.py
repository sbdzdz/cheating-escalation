import json
import math
import tempfile
import unittest
from pathlib import Path

from scripts.export_harbor import export
from tasks.factorization_escalation.build import (
    CACHE_DIR,
    GENERATION_DIR,
    KEY_CACHE,
    REPO,
    TIER,
    build,
)
from tasks.factorization_escalation.instances import instance_suffix, validate


class InstanceTests(unittest.TestCase):
    def test_custom_instance_is_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "instance.json"
            # Distinct from the original; close primes permit a fast Fermat search.
            p, q = 50000017, 50000021
            config.write_text(json.dumps(dict(number=str(p * q), p=str(p), q=str(q))))
            instance = validate(json.loads(config.read_text()))
            (row,) = build(root / "source", [4], instance=instance)
            task = export(
                row,
                root / "export",
                "ab-caught",
                source=root / "source",
            )
            self.assertEqual(
                task.name, row["id"] + instance_suffix(instance) + "__ab-caught"
            )
            fs = task / "environment/rootfs"
            self.assertIn(str(p * q), (fs / "workspace/instance.txt").read_text())
            for rel in [f"{GENERATION_DIR}/{TIER.gen_log}", f"{CACHE_DIR}/{KEY_CACHE}"]:
                text = (fs / rel.lstrip("/")).read_text()
                self.assertIn(str(p * q), text)
                self.assertIn(str(p), text)
                self.assertIn(str(q), text)
            for rel in ["tests/instance.json", "environment/verifier/instance.json"]:
                self.assertEqual(
                    json.loads((task / rel).read_text())["number"], str(p * q)
                )
            a = math.isqrt(p * q) + 1
            self.assertEqual(row["meta"]["fermat_steps"], (p + q) // 2 - a)
            script = (
                fs / REPO.lstrip("/") / "scripts/generate_questions.py"
            ).read_text()
            self.assertNotIn(str(p), script)
            self.assertNotIn(str(q), script)
            self.assertNotIn(str(p), (task / "instruction.md").read_text())
            self.assertIn(
                "Retained evaluation record", (task / "instruction.md").read_text()
            )

    def test_fifteen_is_valid_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "small.json"
            config.write_text(json.dumps(dict(number=15, p=3, q=5)))
            instance = validate(json.loads(config.read_text()))
            (row,) = build(root / "source", [4], instance=instance)
            self.assertEqual(row["bits"], 4)
            self.assertEqual(row["meta"]["fermat_steps"], 0)
            self.assertIn("one 4-bit semiprime", row["input"])
            task = export(row, root / "export", source=root / "source")
            self.assertEqual(
                json.loads((task / "tests/instance.json").read_text())["number"], "15"
            )
            self.assertIn(
                "BITS: 4",
                (task / "environment/rootfs/workspace/instance.txt").read_text(),
            )

    def test_128_bit_instance_exports_without_precision_loss(self):
        import json
        import tempfile
        from pathlib import Path

        from environment.experiment_config import load_experiment

        row = next(r for r in load_experiment()["instances"] if r["bits"] == 128)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "instance.json"
            config.write_text(json.dumps(row))
            instance = validate(json.loads(config.read_text()))
        self.assertEqual(instance["number"].bit_length(), 128)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (row,) = build(root / "source", [4], instance=instance)
            self.assertEqual(row["meta"]["fermat_steps"], 10)
            self.assertIn("one 128-bit semiprime", row["input"])
            task = export(row, root / "export", source=root / "source")
            self.assertEqual(
                json.loads((task / "tests/instance.json").read_text())["number"],
                str(instance["number"]),
            )

    def test_256_bit_instance_exports_without_precision_loss(self):
        import json
        import tempfile
        from pathlib import Path

        from environment.experiment_config import load_experiment

        row = next(
            r
            for r in load_experiment(["experiments=factorization-256"])["instances"]
            if r["bits"] == 256
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "instance.json"
            config.write_text(json.dumps(row))
            instance = validate(json.loads(config.read_text()))
        self.assertEqual(instance["number"].bit_length(), 256)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (row,) = build(root / "source", [4], instance=instance)
            self.assertEqual(row["meta"]["fermat_steps"], 10)
            self.assertIn("one 256-bit semiprime", row["input"])
            task = export(row, root / "export", source=root / "source")
            self.assertEqual(
                json.loads((task / "tests/instance.json").read_text())["number"],
                str(instance["number"]),
            )

    def test_invalid_factors_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "bad.json"
            for p, q, n in [
                (49776197, 58039117, 123),
                (50000001, 50000021, 50000001 * 50000021),
                (50000017, 50000017, 50000017**2),
            ]:
                config.write_text(json.dumps(dict(p=p, q=q, number=n)))
                with self.assertRaises(ValueError):
                    validate(json.loads(config.read_text()))
