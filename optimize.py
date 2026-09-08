"""Search deviations from our own policy, and keep the ones that pay.

    .venv/bin/python optimize.py [n_turns] [--seeds=3] [--opp=main.py|tape.json]

FINDINGS 42: a recorded route cannot beat the policy that recorded it -- the best
of 24 scored -142 over 14 held-out seeds -- because a recording is a sample from
the policy, not an optimum. So the search has to be over *deviations from* the
policy rather than over recordings of it.

`main._assign` builds `cand`, every (task, unit) pair on the board in cost order,
and consumes it greedily. `DEVIATE[turn] = k` skips its first k entries on that
turn, forcing the next best assignment. That is legal by construction, which an
edit to a recorded action tape is not, and the search space is (turn, k) over 720
turns rather than raw action space over ~8,600 unit-actions. The result is still
one fixed file: our agent plus a table.

The measurement is exact, not noisy. A single action is worth a few hundred
dollars against a cross-board standard error near 5,000, which would be hopeless
-- but that error comes from varying the board and the opponent. Held fixed, the
environment is deterministic (verified byte-identical on repeat), so a deviation
either helps on these boards or it does not.

Two stages, because most turns will not matter and testing all of them at full
width wastes the budget: screen every candidate on one seed, then confirm the
survivors on the rest. Accepted deviations accumulate, so this is coordinate
descent over turns, and the accumulation is what risks overfitting -- validate on
held-out seeds before believing any of it.
"""
import importlib.util
import multiprocessing as mp
import os
import sys

SEEDS = [7100, 7101, 7102, 7103, 7104, 7105]
HOLDOUT = [7200, 7201, 7202, 7203, 7204, 7205, 7206, 7207]


def _load(path):
    spec = importlib.util.spec_from_file_location("opt_" + os.path.basename(path)[:8], path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _play(job):
    """One game. Returns our reward minus the opponent's."""
    deviate, seed, opp_path = job
    from kaggle_environments import make
    import main
    main.DEVIATE = dict(deviate)
    if opp_path.endswith(".json"):
        import json
        import transfer
        r = json.load(open(opp_path))
        opp = transfer.tape(r["steps"], 1)
    else:
        opp = _load(opp_path).agent
    env = make("kaggriculture", configuration={"seed": seed})
    env.run([main.agent, opp])
    rw = [s["reward"] for s in env.steps[-1]]
    return rw[0] - rw[1]


def score(pool, deviate, seeds, opp):
    return sum(pool.map(_play, [(deviate, s, opp) for s in seeds]))


if __name__ == "__main__":
    n_turns = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 720
    opp = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--opp=")), "main.py")
    width = int(next((a.split("=", 1)[1] for a in sys.argv[1:]
                      if a.startswith("--seeds=")), "3"))
    seeds = SEEDS[:width]
    best = {}
    with mp.Pool(min(6, mp.cpu_count())) as pool:
        base = score(pool, best, seeds, opp)
        base1 = score(pool, best, seeds[:1], opp)   # screen reference, cached
        print(f"baseline margin over {len(seeds)} seeds vs {opp}: {base:+,.0f}", flush=True)
        # Turns are visited in a fixed spread rather than in order, so an early
        # stop still covers the whole season instead of only its first days.
        order = sorted(range(720), key=lambda t: (t * 277) % 720)[:n_turns]
        for i, turn in enumerate(order):
            for k in (1, 2):
                trial = dict(best)
                trial[turn] = k
                if score(pool, trial, seeds[:1], opp) <= base1:
                    continue                      # screen on one seed first
                full = score(pool, trial, seeds, opp)
                if full > base:
                    best, base = trial, full
                    base1 = score(pool, best, seeds[:1], opp)
                    print(f"  turn {turn:>3} k={k}  margin {base:+,.0f}  "
                          f"({len(best)} deviations)", flush=True)
                    break
            if i % 40 == 39:
                print(f"  ... {i + 1}/{len(order)} turns tried, "
                      f"{len(best)} kept, margin {base:+,.0f}", flush=True)
        print(f"\nDEVIATE = {best}")
        hold = score(pool, best, HOLDOUT, opp)
        zero = score(pool, {}, HOLDOUT, opp)
        print(f"held-out {len(HOLDOUT)} seeds: baseline {zero:+,.0f} -> tuned {hold:+,.0f}"
              f"  ({hold - zero:+,.0f})")
