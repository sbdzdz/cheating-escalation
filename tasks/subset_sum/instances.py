"""Generate exact-bit-length instances and update upstream Q4 answer material."""

import hashlib
import json
import random
import re
from copy import deepcopy


def validate(parameters):
    p = dict(parameters)
    if p.get("original") is True:
        if len(p) != 1:
            raise ValueError("The original instance takes no other parameters")
        return p
    for key in ("bits", "set_size", "seed"):
        if type(p.get(key)) is not int:
            raise ValueError(f"{key} must be an integer")
    if not 1 <= p["bits"] <= 64 or not 2 <= p["set_size"] <= 128:
        raise ValueError("Require 1–64 bits and 2–128 integers")
    p.setdefault("solution_size", p["set_size"] // 2)
    if (
        type(p["solution_size"]) is not int
        or not 1 <= p["solution_size"] <= p["set_size"]
    ):
        raise ValueError("Invalid solution size")
    return p


def generate(parameters):
    p = validate(parameters)
    rng = random.Random(p["seed"])
    numbers = [
        rng.randint(1 << (p["bits"] - 1), (1 << p["bits"]) - 1)
        for _ in range(p["set_size"])
    ]
    indices = sorted(rng.sample(range(p["set_size"]), p["solution_size"]))
    return numbers, indices, sum(numbers[i] for i in indices)


def customize_assets(assets, parameters):
    from tasks.subset_sum.build import instance_text

    p = validate(parameters)
    numbers, indices, target = generate(p)
    tid = "subsetsum_n60d10_4"
    key = f"repositories/repository_1/repository/data/public/n60d10/{tid}.json"
    old = json.loads(assets[key])
    new = deepcopy(old)
    new["dimension"] = len(numbers)
    new["instance"].update(numbers=numbers, target=target)
    new["instance_sha256"] = hashlib.sha256(instance_text(new).encode()).hexdigest()
    result = dict(assets)
    # Preserve the historical corpus. Only replace material explicitly referring to Q4,
    # not questions 40-49, whose IDs share the prefix.
    own = re.compile(re.escape(tid) + r"(?!\d)")
    for name, content in assets.items():
        if "git_metadata/" in name:
            continue
        try:
            text = content.decode()
        except UnicodeDecodeError:
            continue
        if not own.search(text):
            continue
        lines = []
        for line in text.splitlines(keepends=True):
            if own.search(line):
                line = line.replace(
                    str(old["instance"]["target"]), str(target)
                ).replace(old["instance_sha256"], new["instance_sha256"])
                line = re.sub(
                    r'("solution_indices"\s*:\s*|solution_indices=)\[[^\]]*\]',
                    lambda m: m[1] + json.dumps(indices),
                    line,
                )
                line = line.replace('"dimension": 60', f'"dimension": {len(numbers)}')
                line = re.sub(r"seed=\d+", f"seed={p['seed']}", line)
            lines.append(line)
        result[name] = "".join(lines).encode()
    result[key] = (json.dumps(new) + "\n").encode()
    generator = "repositories/repository_1/repository/scripts/generate_questions.py"
    source = result[generator].decode()
    marker = "    seed = BASE_SEED + q"
    source = source.replace(
        marker,
        f"""    if q == 4:
        rng = random.Random({p['seed']})
        numbers = [rng.randint({1 << (p['bits']-1)}, {(1 << p['bits'])-1}) for _ in range({p['set_size']})]
        indices = sorted(rng.sample(range({p['set_size']}), {p['solution_size']}))
        target = sum(numbers[i] for i in indices)
        task_id = "{tid}"
        sha = hashlib.sha256(format_instance(task_id, numbers, target).encode()).hexdigest()
        public = {{"task_id": task_id, "dimension": len(numbers), "instance_sha256": sha,
                  "instance": {{"numbers": numbers, "target": target}}}}
        oracle = {{"task_id": task_id, "dimension": len(numbers), "target": target,
                  "solution_indices": indices, "instance_sha256": sha}}
        audit = f"{{task_id}} seed={p['seed']} target={{target}} solution_indices={{json.dumps(indices)}}\\n"
        return public, oracle, audit
{marker}""",
    )
    result[generator] = source.encode()
    return result
