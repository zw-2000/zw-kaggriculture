"""Out-of-sample confirmation on seeds that have never picked a value.

    .venv/bin/python oos.py 1 STRAW_MIN=0,8      # round 1

`validate.py`'s OOS_SEEDS has now chosen an adopted value at least four times
(FINDINGS 2.4), so it is a second training set and cannot confirm anything.
This derives a fresh 60-seed set per round from the round number instead, and
prints it, so a later round can never silently reuse an earlier one. Seeds are
drawn above 300 and so are disjoint from bench.SEEDS (the primes 1..283) by
construction.
"""
import itertools
import multiprocessing as mp
import random
import statistics
import sys

import bench


def seeds_for(rnd, n=60):
    return sorted(random.Random(f"kaggriculture-round-{rnd}").sample(range(300, 30000), n))


def go(cfg, opponent, seeds):
    jobs = [(cfg, opponent, s, seat) for s in seeds for seat in (0, 1)]
    with mp.Pool(min(6, mp.cpu_count())) as pool:
        return [(m, t) for _, m, t in pool.map(bench._run, jobs)]


if __name__ == "__main__":
    rnd = int(sys.argv[1])
    opponent = next((a for a in sys.argv[2:] if "=" not in a), "baseline.py")
    seeds = seeds_for(rnd)
    print(f"round {rnd} vs {opponent}: {len(seeds)} fresh seeds {seeds[:6]}...{seeds[-1]}")
    grid = {}
    for a in sys.argv[2:]:
        if "=" in a:
            k, vals = a.split("=", 1)
            grid[k] = [float(v) if "." in v else int(v) for v in vals.split(",")]
    arms = [dict(zip(grid, c)) for c in itertools.product(*grid.values())] if grid else []
    print(f"{'W-L-T':>14} {'score':>7} {'seat0':>6} {'seat1':>6} {'mean':>9} {'worst':>9}   config")
    for cfg in arms or [{}]:
        got = go(cfg, opponent, seeds)
        mine = [m for m, _ in got]
        w = sum(1 for m, t in got if m > t)
        ties = sum(1 for m, t in got if m == t)
        s0 = sum(1 for i, (m, t) in enumerate(got) if i % 2 == 0 and m > t)
        s1 = sum(1 for i, (m, t) in enumerate(got) if i % 2 == 1 and m > t)
        label = "  ".join(f"{k}={v}" for k, v in cfg.items()) or "(defaults)"
        rec = f"{w}-{len(got) - w - ties}-{ties}"
        print(f"{rec:>14} {w + ties / 2:>6.0f}/{len(got):<3} {s0:>6} {s1:>6} {statistics.mean(mine):>9,.0f} "
              f"{min(mine):>9,.0f}   {label}", flush=True)
