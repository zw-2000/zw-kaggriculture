"""Record our own agent's action sequence as a replayable route.

    .venv/bin/python route.py <seed> [out.json] [--agent=main.py] [NAME=value ...]

FINDINGS 39 measured that a recorded 720-turn action sequence keeps 93%-144% of
its home score on boards it never saw, because the farm is a deterministic grid
and only weeds and the shop lottery vary. That is what makes the leaders' stored
routes work.

Nothing about that property is theirs. This records *our* agent playing a seed
and writes the result in the same shape a Kaggle replay has, so `transfer.py`
can score it on any other board with no special cases. If our routes transfer
too, a route is something we can search for rather than something to copy.

The opponent is our own agent unless one is named, so the recorded trajectory is
the one our policy produces in a real contested market rather than against a
passive board.
"""
import importlib.util
import json
import sys


def load(path):
    spec = importlib.util.spec_from_file_location("route_" + path.replace("/", "_")[:20], path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def record(seed, agent, opponent, overrides=None):
    from kaggle_environments import make

    env = make("kaggriculture", configuration={"seed": seed})
    env.run([agent, opponent])
    steps = [[{"action": s.get("action"), "reward": s.get("reward")} for s in turn]
             for turn in env.steps]
    return {
        # Shaped like a downloaded replay so transfer.py needs no special case.
        "info": {"TeamNames": ["OURS", "OPP"], "seed": seed},
        "configuration": {k: v for k, v in env.configuration.items()
                          if k not in ("agentTimeout", "actTimeout", "runTimeout")},
        "steps": steps,
    }, [s["reward"] for s in env.steps[-1]]


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    seed = int(args[0])
    out = next((a for a in args[1:] if a.endswith(".json")), f"/tmp/route-{seed}.json")
    path = next((a.split("=", 1)[1] for a in args if a.startswith("--agent=")), "main.py")
    m = load(path)
    for a in args:
        if "=" in a and not a.startswith("--") and not a.endswith(".json"):
            k, v = a.split("=", 1)
            if not hasattr(m, k):
                raise AttributeError(f"{k!r} is not defined in {path}")
            setattr(m, k, float(v) if "." in v else int(v))
            print(f"override {k}={v}")
    # A second, unswept instance: setattr on one must not reach the opponent.
    opp = load(path)
    replay, rewards = record(seed, m.agent, opp.agent)
    # transfer.py reads the tape from seat 1 by default; ours is seat 0, so store
    # the trajectory in seat 1's slot as well to keep that default working.
    for turn in replay["steps"]:
        turn[1] = dict(turn[0])
    json.dump(replay, open(out, "w"))
    print(f"seed {seed}  ours {rewards[0]:,.0f} vs {rewards[1]:,.0f}  -> {out}")
