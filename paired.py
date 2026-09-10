"""Paired margin between two configs of main.py against one fixed opponent.

    .venv/bin/python paired.py pub_router.py GOOSE_CAP=0 GOOSE_CAP=6
    .venv/bin/python paired.py --demo

`bench.py` ranks on wins, and against an opponent we never beat every arm reads
0-120, so the win column carries no information and the only readable signal is
production. A mean difference of two bench rows is not a result on its own: the
board re-draw swings +/-19,600 a game. Pairing by (seed, seat) removes the board
and gives the standard error the arms have to clear (GATES G14, FINDINGS 47).

Reuses bench.SEEDS and bench._run so the games are the identical games bench
runs; this file only changes how they are scored.
"""
import multiprocessing as mp
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
    with mp.Pool(min(6, mp.cpu_count())) as pool:
        res = pool.map(bench._run, jobs)
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
    mean = statistics.mean(deltas)
    se = statistics.stdev(deltas) / len(deltas) ** 0.5 if len(deltas) > 1 else 0.0
    return mean, se, sum(1 for d in deltas if d > 0), len(deltas)


def demo():
    """A config paired against itself must be exactly zero, on every board."""
    seeds = bench.SEEDS[:4]
    mean, se, up, n = compare("pub_router.py", {"HERD_CAP": 13}, {"HERD_CAP": 13}, seeds)
    assert n == 2 * len(seeds), n
    assert mean == 0.0 and se == 0.0 and up == 0, (mean, se, up)
    print("PAIRED_CHECKS_PASSED")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        opp = sys.argv[1]
        a, b = _parse(sys.argv[2]), _parse(sys.argv[3])
        mean, se, up, n = compare(opp, a, b)
        sigma = mean / se if se else float("inf") if mean else 0.0
        print(f"{sys.argv[3]} over {sys.argv[2]} vs {opp}: "
              f"{mean:+,.0f}/game  se {se:,.0f}  {sigma:+.2f} sigma  "
              f"{up}/{n} boards up")
