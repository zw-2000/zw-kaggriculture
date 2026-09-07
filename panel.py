"""Score main.py against frozen live opponents, on the boards they really played.

    .venv/bin/python panel.py /tmp/kagg-replays/episode-*.json

Every opponent in `bench.py`'s pool -- v27, v17, opp_herd, opp_crop,
opp_notomato -- is one of our own ancestors, so every measurement this project
has made is against a field that does not exist. FINDINGS 28 fingerprinted three
live opponents as one copied public agent, and FINDINGS 30 identified it as a
stored 720-turn action tape.

A tape can be replayed. `replay_check.py` already proves the installed simulator
reproduces a live season exactly from `replay["configuration"]` plus
`replay["info"]["seed"]` (gate G6), so re-running a recorded episode at its own
seed with our current agent substituted into our seat answers the only question
that matters: would today's agent have won the game we actually lost?

The known limitation, which the top-ten notebook that uses this method states
about its own panels: a taped opponent cannot react to us. Once our play moves
the shared market its recorded orders drift out of legality and the tape
degrades. It is still a far better opponent than a copy of ourselves, and the
degradation is one-sided against us -- the tape never gets to adapt.
"""
import importlib.util
import json
import sys

TEAM = "Zhian Wei"


def tape(steps, seat):
    """Play the recorded action stream for `seat`, then PASS past the end."""
    i = [0]

    def act(_obs, _cfg=None):
        n = i[0]
        i[0] += 1
        # steps[0] is the initial state; actions start at the same index the
        # environment asks for them, one per call, exactly as recorded.
        if n + 1 < len(steps):
            return steps[n + 1][seat]["action"]
        return {}

    return act


def replay_against(path, agent):
    from kaggle_environments import make

    replay = json.load(open(path))
    names = replay["info"]["TeamNames"]
    mine = names.index(TEAM) if TEAM in names else 0
    steps = replay["steps"]
    config = dict(replay["configuration"], seed=replay["info"]["seed"])

    env = make("kaggriculture", configuration=config)
    seats = [None, None]
    seats[mine] = agent
    seats[1 - mine] = tape(steps, 1 - mine)
    env.run(seats)

    now = [s["reward"] for s in env.steps[-1]]
    was = [s.get("reward") for s in steps[-1]]
    return {
        "path": path.rsplit("/", 1)[-1],
        "opponent": names[1 - mine],
        "was_us": was[mine], "was_opp": was[1 - mine],
        "now_us": now[mine], "now_opp": now[1 - mine],
    }


if __name__ == "__main__":
    paths = [a for a in sys.argv[1:] if "=" not in a]
    if not paths:
        raise SystemExit(__doc__)
    spec = importlib.util.spec_from_file_location("panel_main", "main.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # Same NAME=value convention as bench.py, and the same guard: a name main.py
    # does not define would setattr silently and measure nothing.
    for a in sys.argv[1:]:
        if "=" in a:
            k, v = a.split("=", 1)
            if not hasattr(m, k):
                raise AttributeError(f"{k!r} is not defined in main.py")
            setattr(m, k, float(v) if "." in v else int(v))
            print(f"override {k}={v}")

    print(f"{'recorded':>19}  {'replayed':>19}   {'':>6}  opponent")
    flips = kept = 0
    for p in paths:
        r = replay_against(p, m.agent)
        won_before = r["was_us"] > r["was_opp"]
        won_now = r["now_us"] > r["now_opp"]
        mark = "WIN " if won_now else "LOSS"
        if won_now != won_before:
            mark += " *FLIP*"
            flips += 1
        else:
            kept += 1
        print(f'{r["was_us"]:>9,.0f}v{r["was_opp"]:>9,.0f}  '
              f'{r["now_us"]:>9,.0f}v{r["now_opp"]:>9,.0f}   {mark:>11}  {r["opponent"]}')
    print(f"{kept} unchanged, {flips} flipped")
