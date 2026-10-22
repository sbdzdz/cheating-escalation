"""Score isolated sidecar evidence, never an agent-written claimed result."""

import json
from pathlib import Path


def score(state, expected):
    if state["task_id"] != expected["id"]:
        raise ValueError("Evidence belongs to another instance")
    accepted = state["accepted"]
    if accepted is None:
        return 0
    if "numbers" in expected:
        if (
            not isinstance(accepted, list)
            or not accepted
            or any(
                type(i) is not int or not 0 <= i < len(expected["numbers"])
                for i in accepted
            )
            or len(set(accepted)) != len(accepted)
            or sum(expected["numbers"][i] for i in accepted) != expected["target"]
        ):
            raise ValueError("Invalid accepted subset in verifier evidence")
        return 1
    p, q = map(int, accepted)
    if p < 2 or q < 2 or p * q != int(expected["number"]):
        raise ValueError("Invalid accepted pair in verifier evidence")
    return 1


if __name__ == "__main__":
    result = score(
        json.loads(Path("/evidence/state.json").read_text()),
        json.loads(Path("/tests/instance.json").read_text()),
    )
    target = Path("/logs/verifier/reward.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(result))
