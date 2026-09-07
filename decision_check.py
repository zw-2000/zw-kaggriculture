"""Verify a frozen submission against its live decisions.

    .venv/bin/python decision_check.py v27.py replay.json 1
"""
import copy
import importlib.util
import json
import sys


def check(agent_path, replay_path, seat):
    if seat not in (0, 1):
        raise ValueError("seat must be 0 or 1")
    spec = importlib.util.spec_from_file_location("frozen_agent", agent_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with open(replay_path) as source:
        steps = json.load(source)["steps"]
    if len(steps) < 2:
        raise ValueError("Replay must contain played turns")
    for turn, (before, after) in enumerate(zip(steps, steps[1:])):
        obs = copy.deepcopy(before[seat]["observation"])
        obs.update(player=seat, step=turn)
        actual = module.agent(obs)
        expected = after[seat]["action"]
        if actual != expected:
            raise AssertionError(f"Decision differs at turn {turn}: "
                                 f"actual={actual!r}, recorded={expected!r}")
    print(f"DECISION_PARITY_PASSED {len(steps) - 1} decisions: {agent_path}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: decision_check.py agent.py replay.json seat")
    check(sys.argv[1], sys.argv[2], int(sys.argv[3]))
