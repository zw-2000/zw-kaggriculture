"""Does a top agent's recorded action tape still work on a board it never saw?

    .venv/bin/python transfer.py <tape-replay.json> <board-replay.json> [...]

FINDINGS 30 identified the field's leaders as replaying a stored 720-turn action
route with a few observation-gated branches. Their submission is a single fixed
file that must face every board the ladder deals, so either those routes
generalise across boards or the method is not what it looks like.

This lifts the recorded action stream out of one episode and plays it, turn for
turn, on a *different* episode's seed and configuration, against our own agent.
If it scores near what it scored at home, the route is board-independent and
route search is reachable for us. If it collapses, their tape is doing something
our reading of it does not capture.

A board argument may be a replay path or `seed:N`. Because the route is
board-independent (measured: 93%-144% of home on unseen boards, never a
collapse), any seed is a legal board, so the supply of benchmark games is
unlimited -- which lifts the 109-board ceiling panel.py works under. The tape
replay's own configuration is reused so only the seed varies.

Control: replaying a tape on its own board reproduces the recorded score
exactly, which panel.py already relies on.
"""
import json
import sys

from panel import tape


def load(path, seat=None):
    r = json.load(open(path))
    names = r["info"]["TeamNames"]
    if seat is None:
        seat = 1
    return r, names, seat


def run(tape_path, board_path, agent):
    from kaggle_environments import make

    tr, tnames, tseat = load(tape_path)
    if board_path.startswith("seed:"):
        config = dict(tr["configuration"], seed=int(board_path[5:]))
    else:
        br, bnames, _ = load(board_path)
        config = dict(br["configuration"], seed=br["info"]["seed"])
    env = make("kaggriculture", configuration=config)
    # Tape in seat 0, our agent in seat 1: the tape's own farm is the one it
    # scripted, so give it the seat its coordinates were written for.
    env.run([tape(tr["steps"], tseat), agent])
    r = [s["reward"] for s in env.steps[-1]]
    home = tr["steps"][-1][tseat].get("reward")
    return tnames[tseat], home, r[0], r[1]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    import importlib.util
    spec = importlib.util.spec_from_file_location("tmain", "main.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    tape_path, boards = sys.argv[1], sys.argv[2:]
    # Sweep overrides on our side, same NAME=value convention as bench.py.
    for a in list(boards):
        if "=" in a and not a.startswith("--"):
            boards.remove(a)
            k, v = a.split("=", 1)
            if not hasattr(m, k):
                raise AttributeError(f"{k!r} is not defined in main.py")
            setattr(m, k, float(v) if "." in v else int(v))
            print(f"override {k}={v}")
    wins = []
    print(f"{'tape owner':<18}{'home':>10}{'away':>10}{'kept':>7}{'us':>10}  board")
    for b in boards:
        who, home, away, us = run(tape_path, b, m.agent)
        same = "OWN" if b == tape_path else ""
        wins.append(us > away)
        print(f"{who[:18]:<18}{home:>10,.0f}{away:>10,.0f}"
              f"{away / home if home else 0:>6.0%}{us:>10,.0f}  {b.rsplit('/', 1)[-1][:28]} {same}")
    if wins:
        print(f"OUR RECORD {sum(wins)}-{len(wins) - sum(wins)} of {len(wins)}")
