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


def pool():
    """A worker pool with a parallelism cap.

    BENCH_PROCS caps workers when something else on the box is resident; a
    480-game paired run was killed twice for system memory. `maxtasksperchild`
    was added in the same change on the theory that `_run` leaks a game's env
    per task -- MEASURED AND WRONG: one process running six games peaks at
    290 MB and grows about 1 MB a game, so 4 workers is ~1.2 GB and the kills
    are system-wide pressure, not this. The recycling is kept because it costs
    nothing; the cap is the part that matters. Run one opponent per invocation
    under `python -u` if a run is being killed, so a completed opponent row
    survives the next one dying.
    """
    n = int(os.environ.get("BENCH_PROCS", 0)) or min(6, mp.cpu_count())
    return mp.Pool(n, maxtasksperchild=8)


def _pristine():
    """A second, unswept instance of main.py -- setattr on one must not reach it."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    spec = importlib.util.spec_from_file_location("main_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _decouple_town():
    """Common random numbers for the town (BENCH_CRN=1).

    `_end_of_day` builds one RNG per day from (seed, day); both farms' weed spawns
    draw from it first -- one draw per EMPTY tile -- and only then is the day's
    shop chosen. So any lever that changes how many tiles stand empty re-rolls the
    whole season's shop lottery, which is the demand side of the economy. Measured:
    on seed 1 the shipped agent's town opened three PIZZA_SHOPs and three
    ICE_CREAM_SHOPs, the same seed under a stickiness arm opened one of each, and
    milk sold at $34 instead of $130 FOR BOTH PLAYERS. Pairing by seed cancelled
    the board and not the market (FINDINGS 59).

    Weeds here draw from a copy of the day's RNG state, one copy per farm, so each
    farm's weeds still depend on its own empty tiles -- that part of a lever's
    effect is real -- while the shop draw sees the untouched RNG and is identical
    across arms. Towns stay uniformly random per seed; only the coupling goes.
    """
    import random
    from kaggle_environments.envs.kaggriculture import kaggriculture as K
    if getattr(K._spawn_weeds, "_crn", False):
        return
    orig, last = K._spawn_weeds, {"rng": None, "k": 0}

    def spawn(farm, board_size, weed_chance, rng):
        if last["rng"] is not rng:
            last["rng"], last["k"] = rng, 0
        own = random.Random(f"{rng.getstate()!r}/{last['k']}")
        last["k"] += 1
        return orig(farm, board_size, weed_chance, own)
    spawn._crn = True
    K._spawn_weeds = spawn


def _run(job):
    cfg, opponent, seed, seat = job
    import main
    from kaggle_environments import make
    if os.environ.get("BENCH_CRN") == "1":
        _decouple_town()
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
    return cfg, r[seat], r[1 - seat], opponent


def main_():
    args = [a for a in sys.argv[1:]]
    # A pool, not one opponent: a mirror benchmark cannot score a shape change
    # that only pays against a varied field (FINDINGS 13.10). Comma-separate to
    # run every config against every opponent and rank on the pooled score.
    opponents = next((a for a in args if "=" not in a), "self").split(",")
    grid = {}
    for a in args:
        if "=" in a:
            k, vals = a.split("=", 1)
            grid[k] = [float(v) if "." in v else int(v) for v in vals.split(",")]
    cfgs = ([dict(zip(grid, c)) for c in itertools.product(*grid.values())]
            if grid else [{}])

    jobs = [(c, o, s, seat)
            for c in cfgs for o in opponents for s in SEEDS for seat in (0, 1)]
    with pool() as p:
        res = p.map(_run, jobs)

    rows = []
    for cfg in cfgs:
        got = [(m, t) for c, m, t, _ in res if c == cfg]
        mine = [m for m, _ in got]
        rows.append((statistics.mean(mine), statistics.median(mine), min(mine),
                     sum(1 for m, t in got if m > t), len(got), cfg,
                     sum(1 for m, t in got if m == t)))
    # Rank by wins, not money. The leaderboard is a skill rating driven by
    # head-to-head results, and the two diverge violently: LAND_USE=2.0 earns
    # 52k against the default's 59k while winning 3 games of 48, because
    # producing less leaves shared market capacity for the opponent to sell into.
    # Rank on the Elo convention, score = wins + ties/2, not on raw wins. With no
    # ties the two are identical, so every result measured before ties appeared
    # stays comparable. With ties they diverge and raw wins inverts the answer:
    # LAND_DAY4=12 scored 48 wins / 0 ties against a mirror control's 38 wins /
    # 44 ties, which reads as +10 on wins and is really 48W-72L against an even
    # 38W-38L -- the control's "missing" wins are ties, not losses.
    rows.sort(key=lambda r: (r[3] + r[6] / 2, r[0]), reverse=True)
    # Ties are reported because they are not rare: a true mirror at PRIO_WEIGHT=1
    # ends 19 win / 19 loss / 22 tie over 60 games, so the null is 38/120 rather
    # than the ~59/120 that held at PRIO_WEIGHT=14. Printing wins alone makes a
    # tie indistinguishable from a loss and silently moves the null under you.
    print(f"{'mean':>9} {'median':>9} {'worst':>9} {'W-L-T':>14} {'score':>7}   config")
    for mean, med, worst, wins, n, cfg, ties in rows:
        label = "  ".join(f"{k}={v}" for k, v in cfg.items()) or f"(defaults, vs {','.join(opponents)})"
        rec = f"{wins}-{n - wins - ties}-{ties}"
        print(f"{mean:>9,.0f} {med:>9,.0f} {worst:>9,.0f} {rec:>14} "
              f"{wins + ties / 2:>6.0f}/{n:<3}   {label}")
        if len(opponents) > 1:
            # Pooled score hides non-transitivity, which is the whole reason the
            # pool exists. Print the per-opponent split under every config.
            for o in opponents:
                sub = [(m, t) for c, m, t, oo in res if c == cfg and oo == o]
                w = sum(1 for m, t in sub if m > t)
                ti = sum(1 for m, t in sub if m == t)
                print(f"{'':>9} {'':>9} {'':>9} "
                      f"{f'{w}-{len(sub) - w - ti}-{ti}':>14} "
                      f"{w + ti / 2:>6.0f}/{len(sub):<3}     vs {o}")


if __name__ == "__main__":
    main_()
