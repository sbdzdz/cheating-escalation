"""Task definitions shared by batch preparation, export and individual runs."""

import hashlib
import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from harbor_adapter.conditions import TASK_CONDITION_PROMPTS


@dataclass(frozen=True)
class Task:
    kind: str
    package: str

    @property
    def harbor(self):
        return import_module(f"{self.package}.harbor_task")

    def validate(self, instance):
        return import_module(f"{self.package}.instances").validate(instance)

    def check_condition(self, condition):
        if (
            condition != "baseline"
            and condition not in TASK_CONDITION_PROMPTS[self.kind]
        ):
            raise ValueError(f"{self.kind} does not support condition {condition}")

    def build(self, output, questions, instance=None):
        questions = list(questions)
        instance = self.validate(instance) if instance is not None else None
        build = import_module(f"{self.package}.build").build
        if self.kind == "subset_sum":
            if instance and not instance.get("original") and questions != [4]:
                raise ValueError("Custom subset-sum instances require question 4")
            return build(
                output,
                questions,
                parameters=None if instance and instance.get("original") else instance,
            )
        return build(output, questions, instance=instance)

    def name(self, question=4, instance=None, condition="baseline"):
        self.check_condition(condition)
        if type(question) is not int or not 4 <= question <= 100:
            raise ValueError("question must be an integer in 4..100")
        instance = self.validate(instance) if instance is not None else None
        if self.kind == "factorization":
            name = f"fact_n52_{question}"
            if instance is not None:
                name += import_module(f"{self.package}.instances").instance_suffix(
                    instance
                )
        else:
            name = f"subsetsum_n60d10_{question}"
            if instance and not instance.get("original"):
                if question != 4:
                    raise ValueError("Custom subset-sum instances require question 4")
                name += (
                    "__"
                    + hashlib.sha256(
                        json.dumps(instance, sort_keys=True).encode()
                    ).hexdigest()[:12]
                )
        return name if condition == "baseline" else name + "__" + condition


TASKS = {
    "factorization": Task("factorization", "tasks.factorization_escalation"),
    "subset_sum": Task("subset_sum", "tasks.subset_sum"),
}


def get_task(kind):
    try:
        return TASKS[kind]
    except KeyError:
        raise ValueError(f"Unknown task: {kind}") from None


def resolve_task(
    task_kind,
    *,
    question=4,
    instance=None,
    condition="baseline",
    task_path=None,
    output=None,
):
    """Explicit snapshots are authoritative; otherwise use the export naming rules."""
    if task_path is not None:
        return Path(task_path)
    if isinstance(instance, (str, Path)):
        instance = json.loads(Path(instance).read_text())
    output = (
        Path(output)
        if output is not None
        else Path(__file__).resolve().parents[1] / "generated/harbor"
    )
    return output / get_task(task_kind).name(question, instance, condition)
