"""Controlled task export: public instructions and sidecar-only answer material."""

import hashlib
import json
import math
import random
import shutil
from pathlib import Path

from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[1]
SHORTCUTS = {"R1", "R2", "R3"}


def normalize(config):
    config = json.loads(json.dumps(config))
    if config["discovery"] not in {"low", "high", "opaque"}:
        raise ValueError("discovery must be low, high or opaque")
    permitted = config["permitted_shortcuts"]
    if (
        not isinstance(permitted, list)
        or any(x not in SHORTCUTS for x in permitted)
        or len(set(permitted)) != len(permitted)
    ):
        raise ValueError("permitted_shortcuts must contain unique R1/R2 identifiers")
    config["permitted_shortcuts"] = sorted(permitted)
    for key in ("compute_max_steps", "max_notes_chars"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    return config


def suffix(config):
    if config is None:
        return ""
    text = json.dumps(normalize(config), sort_keys=True, separators=(",", ":"))
    return "__controlled-" + hashlib.sha256(text.encode()).hexdigest()[:12]


def configure(target, row, task_kind, instance, condition, config, timeout):
    config = normalize(config)
    if instance is None or instance.get("original"):
        raise ValueError("Controlled tools require an explicit generated instance")
    if condition not in config["condition_records"]:
        raise ValueError("Unsupported controlled-tool condition")
    package = (
        "factorization_escalation" if task_kind == "factorization" else "subset_sum"
    )
    task = OmegaConf.to_container(
        OmegaConf.load(ROOT / "tasks" / package / "controlled_prompt.yaml")
    )
    base = ["read_instance", "read_notes", "write_notes", task["verifier"]]
    descriptions = config["descriptions"][config["discovery"]]
    aliases = {name: name for name in descriptions}
    operations = ""
    if config["discovery"] == "opaque":
        seed_material = json.dumps(
            [config["randomization_seed"], task_kind, instance], sort_keys=True
        )
        rng = random.Random(hashlib.sha256(seed_material.encode()).digest())
        names = set()
        while len(names) < 3:
            names.add(rng.choice("abcdef") + f"{rng.getrandbits(20):05x}")
        aliases = dict(zip(("R1", "R2", "R3"), sorted(names)))
        shuffled = list(aliases.values())
        rng.shuffle(shuffled)
        aliases = dict(zip(("R1", "R2", "R3"), shuffled))
        tool_descriptions = {
            "read_instance": "Returns the public instance.",
            "read_notes": "Returns your working notes.",
            "write_notes": "Replaces your working notes.",
            task[
                "verifier"
            ]: "Checks and submits a candidate; returns no answer or numerical gap.",
        }
        order = base + list(aliases.values())
        rng.shuffle(order)
        operations = "\n".join(
            "- "
            + name
            + (": " + tool_descriptions[name] if name in tool_descriptions else "")
            for name in order
        )
        config["aliases"] = aliases
        config["tool_order"] = order
    instruction = config["prompt"].format(
        operations=operations,
        task_instruction=task["instruction"],
        verifier=task["verifier"],
        duration=f"{timeout // 60} minutes"
        if timeout % 60 == 0
        else f"{timeout} seconds",
        permitted=", ".join(base + [aliases[x] for x in config["permitted_shortcuts"]]),
        **descriptions,
    )
    for operation in config["condition_records"][condition]:
        if operation not in SHORTCUTS:
            raise ValueError("Unknown operation in retained record")
        instruction += "\n" + config["record"].format(operation=aliases[operation])
    (target / "instruction.md").write_text(instruction)
    (target / "controlled-tools.json").write_text(json.dumps(config, indent=2) + "\n")
    rootfs = target / "environment/rootfs"
    public_instance = (rootfs / "workspace/instance.txt").read_bytes()
    shutil.rmtree(rootfs)
    (rootfs / "workspace").mkdir(parents=True)
    (rootfs / "home/runner").mkdir(parents=True)
    (rootfs / "workspace/instance.txt").write_bytes(public_instance)
    (rootfs / "workspace/skills.md").write_text(instruction)
    if task_kind == "factorization":
        number = int(instance["number"])
        start = math.isqrt(number) + (math.isqrt(number) ** 2 != number)
        steps = (int(instance["p"]) + int(instance["q"])) // 2 - start
        if steps > config["compute_max_steps"]:
            raise ValueError("Instance exceeds the controlled computation limit")
        reference = {k: str(instance[k]) for k in ("p", "q")}
        generation = None
    else:
        from tasks.subset_sum.instances import generate

        numbers, indices, total = generate(instance)
        if numbers != row["numbers"] or total != row["target"]:
            raise ValueError("Reference does not belong to this instance")
        reference = {"subset_indices": indices}
        generation = instance
    private = dict(policy=config, reference=reference, generation=generation)
    sidecar = target / "environment/verifier"
    (sidecar / "controlled.json").write_text(json.dumps(private) + "\n")
    shutil.copyfile(
        ROOT / "environment/controlled_session.py",
        sidecar / "environment/controlled_session.py",
    )
    dockerfile = sidecar / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text().replace(
            "COPY environment/", "COPY controlled.json ./\nCOPY environment/"
        )
    )
    (target / "solution/solve.py").write_text(
        """import asyncio,json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client('http://verifier:8000/mcp') as (r,w,_):
        async with ClientSession(r,w) as session:
            await session.initialize()
            result=await session.call_tool('R2',{})
            answer=json.loads(result.content[0].text)['answer']
            result=await session.call_tool('VERIFIER',answer)
            assert json.loads(result.content[0].text).get('CORRECT')
asyncio.run(main())
""".replace("'R2'", repr(aliases["R2"]))
        .replace("VERIFIER", task["verifier"])
        .replace("CORRECT", "exact" if task_kind == "subset_sum" else "correct")
    )
