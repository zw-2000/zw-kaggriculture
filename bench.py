"""Benchmark across seeds and seats, or sweep parameters.

    .venv/bin/python bench.py                          # 8 seeds x 2 seats vs self
    .venv/bin/python bench.py starter                  # different opponent
    .venv/bin/python bench.py self MELON_TILES=16,22,30
    .venv/bin/python bench.py starter MELON_TILES=16,22 WHEAT_FRACTION=0.3,0.45

Any `NAME=v1,v2` argument sweeps that module-level constant in main.py; the
cartesian product is run and ranked. Seeds matter: weed spawns and shop-unlock
order are random, and differences under ~6 seeds are usually noise.

The default opponent is `self`: an unmodified copy of main.py, so a sweep
measures the swept value against the version we already have. Tuning against
`starter` measures the wrong game -- it does not contest the market, and the
market is the only thing connecting the two players. The same agent scores
~80k against starter and ~26k against itself, so every constant swept on
starter was fitted to a distribution the leaderboard will never show us.

`self` reads main.py off disk, so it can only measure a *swept constant*. To
measure an edit to the logic, freeze the version you are trying to beat
(`cp main.py baseline.py`) and run `bench.py baseline.py` -- against `self`
both seats change together and the win rate is pinned at half by construction.
"""
import importlib.util
import itertools
import multiprocessing as mp
import os
import statistics
import sys

# 60 seeds x 2 seats = 120 games in ~3min. Was 24 seeds / 48 games, which is not
# enough: a mirror match (an agent against a byte-identical copy of itself) still
# swings +/-$19,600 per game, stdev $7,118, because `_end_of_day` shares one RNG
# between both farms' weed spawns and the town shop lottery, and `_spawn_weeds`
# only draws for *empty* tiles -- so one extra planted tile reshuffles the
# opponent's weeds and the whole season's shop unlocks.
# 48 games resolves about +/-6 wins; 120 is what a real effect of a few thousand
# dollars needs. Rank on wins, never on mean: mean is mostly the re-draw.
SEEDS = [1, 3, 5, 7, 11, 13, 17, 23, 29, 31, 37, 41,
         43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97,
         101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157,
         163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223, 227,
         229, 233, 239, 241, 251, 257, 263, 269, 271, 277, 281, 283]


def _pristine():
    """A second, unswept instance of main.py -- setattr on one must not reach it."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    spec = importlib.util.spec_from_file_location("main_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(job):
    cfg, opponent, seed, seat = job
    import main
    from kaggle_environments import make
    for k, v in cfg.items():
        # A swept name main.py does not define creates a dead module attribute:
        # setattr succeeds, nothing reads it, and the sweep silently measures one
        # config N times and prints it as a comparison. WHEAT_RUSH_DAY did exactly
        # this once it was reverted out of main.py.
        if not hasattr(main, k):
            raise AttributeError(
                f"{k!r} is not defined in main.py -- sweeping it is a silent no-op")
        setattr(main, k, v)
    opp = _pristine().agent if opponent == "self" else opponent
    env = make("kaggriculture", configuration={"seed": seed})
    env.run([main.agent, opp] if seat == 0 else [opp, main.agent])
    r = [s["reward"] for s in env.steps[-1]]
    return cfg, r[seat], r[1 - seat]


def main_():
    args = [a for a in sys.argv[1:]]
    opponent = next((a for a in args if "=" not in a), "self")
    grid = {}
    for a in args:
        if "=" in a:
            k, vals = a.split("=", 1)
            grid[k] = [float(v) if "." in v else int(v) for v in vals.split(",")]
    cfgs = ([dict(zip(grid, c)) for c in itertools.product(*grid.values())]
            if grid else [{}])

    jobs = [(c, opponent, s, seat) for c in cfgs for s in SEEDS for seat in (0, 1)]
    with mp.Pool(min(6, mp.cpu_count())) as pool:
        res = pool.map(_run, jobs)

    rows = []
    for cfg in cfgs:
        got = [(m, t) for c, m, t in res if c == cfg]
        mine = [m for m, _ in got]
        rows.append((statistics.mean(mine), statistics.median(mine), min(mine),
                     sum(1 for m, t in got if m > t), len(got), cfg))
    # Rank by wins, not money. The leaderboard is a skill rating driven by
    # head-to-head results, and the two diverge violently: LAND_USE=2.0 earns
    # 52k against the default's 59k while winning 3 games of 48, because
    # producing less leaves shared market capacity for the opponent to sell into.
    rows.sort(key=lambda r: (r[3], r[0]), reverse=True)  # never compare the cfg dicts
    print(f"{'mean':>9} {'median':>9} {'worst':>9} {'wins':>7}   config")
    for mean, med, worst, wins, n, cfg in rows:
        label = "  ".join(f"{k}={v}" for k, v in cfg.items()) or f"(defaults, vs {opponent})"
        print(f"{mean:>9,.0f} {med:>9,.0f} {worst:>9,.0f} {wins:>3}/{n:<3}   {label}")


if __name__ == "__main__":
    main_()
