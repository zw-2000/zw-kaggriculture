"""Validate the benchmark itself before trusting anything it said.

  V1  determinism      -- same config twice must give byte-identical rewards
  V2  true mirror      -- main.py vs a byte-identical copy: the real parity number
  V3  seat balance     -- wins/ties split by seat
  V4  out-of-sample    -- re-measure an adopted constant on a disjoint seed set

RETIRED: v4, v6, final and rushoos all sweep WHEAT_RUSH_DAY, which no longer
exists in main.py -- it was reverted out in full. bench._run now raises on a
swept name main.py does not define, so those modes fail loud instead of silently
measuring one config twice. To re-run any of them, first restore the constant.

Every mode below names its opponent as a path, except `self` -- which is not a
file but `bench._pristine()`, a second unswept instance of main.py loaded off
disk. That is what V2 wants: a copy that is byte-identical *by construction* and
so can never drift out of date, unlike a checked-in copy that has to be kept
identical by hand. Any opponent that is a real path must be frozen and never
overwritten -- overwriting one makes every number measured against it
permanently uninterpretable, which has happened before. Note baseline.py is
currently byte-identical to main.py too, so
passing it is also a MIRROR, not a head-to-head, until you next `cp` over it.
"""
import multiprocessing as mp
import os
import statistics
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)
sys.path.insert(0, REPO)
import bench  # noqa: E402

# Disjoint from bench.SEEDS (which is the primes 1..283).
OOS_SEEDS = [1009 + 13 * i for i in range(60)]


def go(cfg, opponent, seeds, procs=6):
    jobs = [(cfg, opponent, s, seat) for s in seeds for seat in (0, 1)]
    with mp.Pool(procs) as pool:
        res = pool.map(bench._run, jobs)
    return [(m, t) for _, m, t in res]


def summarise(label, got, seeds):
    mine = [m for m, _ in got]
    wins = sum(1 for m, t in got if m > t)
    ties = sum(1 for m, t in got if m == t)
    # jobs are ordered seed-major, seat-minor
    s0 = sum(1 for i, (m, t) in enumerate(got) if i % 2 == 0 and m > t)
    s1 = sum(1 for i, (m, t) in enumerate(got) if i % 2 == 1 and m > t)
    print(f"{label:<44} wins {wins:>3}/{len(got)}  (seat0 {s0}, seat1 {s1})  "
          f"ties {ties:>2}  mean {statistics.mean(mine):>8,.0f}"
          f"  worst {min(mine):>8,.0f}")
    return wins, mine


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"

    if which in ("all", "v1"):
        print("--- V1: determinism (identical config, run twice) ---")
        # Sweep a constant that still exists, set to its shipped value: exercises
        # the setattr path without changing behaviour. (Was WHEAT_RUSH_DAY=25,
        # which since the 8.4 revert set an attribute nothing reads.)
        a = go({"FERT_CARRY": 2}, "baseline.py", bench.SEEDS[:20])
        b = go({"FERT_CARRY": 2}, "baseline.py", bench.SEEDS[:20])
        print(f"  identical rewards across both runs: {a == b}")
        if a != b:
            diff = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
            print(f"  {len(diff)} of {len(a)} games differ; first: {diff[:3]}")

    if which in ("all", "v2"):
        print("\n--- V2: true mirror on 1.32.6 (main.py vs a byte-identical copy) ---")
        got = go({}, "self", bench.SEEDS)
        summarise("main.py vs identical copy = PARITY", got, bench.SEEDS)

    if which in ("all", "v4"):
        print("\n--- V4: WHEAT_RUSH_DAY out-of-sample (disjoint 60 seeds) ---")
        for v in (99, 25):
            got = go({"WHEAT_RUSH_DAY": v, "FERT_CARRY": 4, "FERT_ONGOING_ONLY": 0},
                     "baseline.py", OOS_SEEDS)
            summarise(f"WHEAT_RUSH_DAY={v} (out-of-sample)", got, OOS_SEEDS)

    if which == "v6":
        # V4 measured the wheat rush inside FERT_ONGOING_ONLY=0, which fertilizes
        # the very wheat the rush plants -- a confound. Re-measure the rush
        # inside the config we would actually ship, on both seed sets.
        print("\n--- V6: wheat rush inside the final fert config, both seed sets ---")
        for name, seeds in (("in-sample", bench.SEEDS), ("out-of-sample", OOS_SEEDS)):
            for v in (99, 25):
                got = go({"WHEAT_RUSH_DAY": v, "FERT_CARRY": 2,
                          "FERT_ONGOING_ONLY": 1}, "baseline.py", seeds)
                summarise(f"WHEAT_RUSH_DAY={v} ({name})", got, seeds)

    if which in ("all", "v5"):
        print("\n--- V5: fertilizer out-of-sample (disjoint 60 seeds) ---")
        for ongoing in (0, 1):
            got = go({"FERT_CARRY": 2, "FERT_ONGOING_ONLY": ongoing,
                      "WHEAT_RUSH_DAY": 25}, "baseline.py", OOS_SEEDS)
            summarise(f"FERT_CARRY=2 FERT_ONGOING_ONLY={ongoing} (oos)",
                      got, OOS_SEEDS)

    if which == "final":
        # The three arms that decide what ships, all on the DISJOINT seed set.
        #   (1) fert pickup, all crops        (2)-(1) = the strawberry-only effect
        #   (2) fert pickup, strawberry only  (2)-(3) = the wheat rush's real value
        #   (3) same, wheat rush disabled
        print("--- FINAL: out-of-sample, 60 disjoint seeds (parity = 57/120) ---",
              flush=True)
        for carry, ongoing, rush in ((2, 0, 25), (2, 1, 25), (2, 1, 99)):
            got = go({"FERT_CARRY": carry, "FERT_ONGOING_ONLY": ongoing,
                      "WHEAT_RUSH_DAY": rush}, "baseline.py", OOS_SEEDS)
            summarise(f"carry={carry} ongoing_only={ongoing} rush={rush}",
                      got, OOS_SEEDS)

    if which == "rushoos":
        # Head-to-head against the NEW agent (newbase.py), disjoint seeds.
        # rush=25 is the mirror control; rush=99 is the candidate revert.
        print("--- rush, head-to-head vs new agent, out-of-sample ---", flush=True)
        for v in (25, 99):
            got = go({"WHEAT_RUSH_DAY": v, "FERT_CARRY": 2,
                      "FERT_ONGOING_ONLY": 1}, "newbase.py", OOS_SEEDS)
            summarise(f"WHEAT_RUSH_DAY={v} vs new agent (oos)", got, OOS_SEEDS)
