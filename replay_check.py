"""Verify the installed simulator against a downloaded Kaggle replay.

    .venv/bin/python replay_check.py path/to/episode-replay.json

Replays recorded actions with the live seed and configuration. Checks both
players after every turn; excludes runtime timing metadata.
"""
import json
import sys


def check(path):
    from kaggle_environments import make

    with open(path) as source:
        replay = json.load(source)
    steps = replay["steps"]
    if len(steps) < 2:
        raise ValueError("Replay must contain played turns")
    config = dict(replay["configuration"], seed=replay["info"]["seed"])
    env = make("kaggriculture", configuration=config)
    for turn, expected in enumerate(steps):
        if turn:
            env.step([state["action"] for state in expected])
        for seat in (0, 1):
            actual = env.steps[-1][seat]
            for field in ("day", "hour", "farms", "market", "private", "town"):
                if actual["observation"][field] != expected[seat]["observation"][field]:
                    raise AssertionError(f"turn={turn} seat={seat} field={field}")
            for field in ("reward", "status"):
                if actual[field] != expected[seat][field]:
                    raise AssertionError(f"turn={turn} seat={seat} field={field}")
    print(f"REPLAY_PARITY_PASSED {len(steps)} states: {path}")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        check(path)
    if len(sys.argv) < 2:
        raise SystemExit("Usage: replay_check.py replay.json [replay.json ...]")
