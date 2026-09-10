"""Paired margin between two configs of main.py, against every opponent given.

    .venv/bin/python paired.py pub_router.py,pub_harvestforge.py FERT_CARRY=3 FERT_CARRY=1
    .venv/bin/python paired.py --demo

PASS MORE THAN ONE OPPONENT. FERT_CARRY=1 measures +2.73 sigma against
pub_router.py and -1.58 sigma against pub_harvestforge.py, 120 games each, and
pools to +668 -- null. The sign is set by which architecture is across the table,
not by the boards, so a single-opponent sigma however large does not say whether
an arm is adoptable (FINDINGS 48). The pooled row is the one G14 reads.

`bench.py` ranks on wins, and against an opponent we never beat every arm reads
0-120, so the win column carries no information and the only readable signal is
production. A mean difference of two bench rows is not a result on its own: the
board re-draw swings +/-19,600 a game. Pairing by (seed, seat) removes the board
and gives the standard error the arms have to clear (GATES G14, FINDINGS 47).

Reuses bench.SEEDS and bench._run so the games are the identical games bench
runs; this file only changes how they are scored.
"""
import statistics
import sys

import bench


def _parse(arg):
    k, v = arg.split("=", 1)
    return {k: float(v) if "." in v else int(v)}


def compare(opponent, cfg_a, cfg_b, seeds=None):
    seeds = seeds or bench.SEEDS
    jobs = [(c, opponent, s, seat)
            for c in (cfg_a, cfg_b) for s in seeds for seat in (0, 1)]
    with bench.pool() as p:
        res = p.map(bench._run, jobs)
    # Keyed by (seed, seat), which is what makes it paired: the same board and
    # the same seating scored under both configs. Split on job index rather than
    # on the returned cfg -- multiprocessing hands back a copy, so identity and
    # equality both fail to tell the two arms apart when they are the same dict.
    half = len(jobs) // 2
    got_a, got_b = {}, {}
    for i, (_c, mine, _theirs, _o) in enumerate(res):
        _cfg, _opp, seed, seat = jobs[i]
        (got_a if i < half else got_b)[(seed, seat)] = mine
    deltas = [got_b[k] - got_a[k] for k in sorted(got_a)]
    return summarise(deltas) + (deltas,)


def summarise(deltas):
    """Aggregates from raw per-board deltas, so chunks run separately can be
    pooled exactly. Pooling means-of-means is only right when the chunks are
    equal-sized, and pooling standard errors from summaries is not right at
    all -- keep the deltas and re-summarise the concatenation."""
    mean = statistics.mean(deltas)
    se = statistics.stdev(deltas) / len(deltas) ** 0.5 if len(deltas) > 1 else 0.0
    return mean, se, sum(1 for d in deltas if d > 0), len(deltas)


def demo():
    """A config paired against itself must be exactly zero, on every board."""
    seeds = bench.SEEDS[:4]
    mean, se, up, n, _d = compare("pub_router.py", {"HERD_CAP": 13}, {"HERD_CAP": 13}, seeds)
    assert n == 2 * len(seeds), n
    assert mean == 0.0 and se == 0.0 and up == 0, (mean, se, up)
    print("PAIRED_CHECKS_PASSED")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        opps = sys.argv[1].split(",")
        a, b = _parse(sys.argv[2]), _parse(sys.argv[3])
        print(f"{sys.argv[3]} over {sys.argv[2]}")
        pooled_mean = pooled_up = pooled_n = 0
        for opp in opps:
            mean, se, up, n, _d = compare(opp, a, b)
            sigma = mean / se if se else 0.0
            print(f"  vs {opp:<24} {mean:+8,.0f}/game  se {se:>6,.0f}  "
                  f"{sigma:+.2f} sigma  {up}/{n} up")
            pooled_mean += mean * n
            pooled_up += up
            pooled_n += n
        if len(opps) > 1:
            print(f"  {'POOLED':<27} {pooled_mean / pooled_n:+8,.0f}/game"
                  f"{'':>16}  {pooled_up}/{pooled_n} up")
