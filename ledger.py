"""Where the 29,532 is: every market dollar, by product and by seat.

    .venv/bin/python ledger.py pub_router.py 1 3 5 7 11
    .venv/bin/python ledger.py --demo

`_commit_unit` (kaggriculture.py:648) is the only place a market op moves money,
so wrapping it gives the settled ledger. versus.py could only report *requested*
quantities, which is why FINDINGS 48 had to instrument by hand to find the
fertilizer leak. Seat is resolved by identity against the farms list
`_process_market` holds, because _commit_unit is handed the farm dict alone.

HIRE and BUY_LAND do not pass through here -- they are not market ops -- so the
ledger accounts for market money only, not the whole money delta.
"""
import sys
from collections import Counter

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture import kaggriculture as K

import main

_farms, _unknown = [], Counter()
_rev = [Counter(), Counter()]
_qty = [Counter(), Counter()]
_spend = [Counter(), Counter()]
_pm, _cu = K._process_market, K._commit_unit


def _wrap_pm(state, env):
    _farms[:] = state[0].observation.farms
    return _pm(state, env)


def _wrap_cu(op, item, price, farm, private, market, shed_capacity=100):
    ok = _cu(op, item, price, farm, private, market, shed_capacity)
    if ok:
        seat = next((i for i, f in enumerate(_farms) if f is farm), None)
        if seat is None:
            _unknown["x"] += 1
        elif op == "SELL":
            _rev[seat][item] += price
            _qty[seat][item] += 1
        else:
            _spend[seat][item] += price
    return ok


K._process_market, K._commit_unit = _wrap_pm, _wrap_cu


def run(opponent, seeds, seat=0):
    for s in seeds:
        env = make("kaggriculture", configuration={"seed": s})
        env.run([main.agent, opponent] if seat == 0 else [opponent, main.agent])
    assert not _unknown, f"{_unknown['x']} commits could not be attributed to a seat"


def report(n, ours, theirs):
    items = sorted(set(_rev[0]) | set(_rev[1]) | set(_spend[0]) | set(_spend[1]))
    print(f"{'item':<12} {'our rev':>9} {'our qty':>8} {'$/u':>6} "
          f"{'their rev':>10} {'their qty':>9} {'$/u':>6} {'delta':>9}")
    for it in items:
        a, b = _rev[ours][it] / n, _rev[theirs][it] / n
        qa, qb = _qty[ours][it] / n, _qty[theirs][it] / n
        print(f"{it:<12} {a:>9,.0f} {qa:>8,.1f} {a / qa if qa else 0:>6,.0f} "
              f"{b:>10,.0f} {qb:>9,.1f} {b / qb if qb else 0:>6,.0f} {a - b:>+9,.0f}")
    ra, rb = sum(_rev[ours].values()) / n, sum(_rev[theirs].values()) / n
    sa, sb = sum(_spend[ours].values()) / n, sum(_spend[theirs].values()) / n
    print(f"{'REVENUE':<12} {ra:>9,.0f} {'':>8} {'':>6} {rb:>10,.0f} "
          f"{'':>9} {'':>6} {ra - rb:>+9,.0f}")
    print(f"{'SPEND':<12} {sa:>9,.0f} {'':>8} {'':>6} {sb:>10,.0f} "
          f"{'':>9} {'':>6} {sa - sb:>+9,.0f}")
    print(f"{'NET MARKET':<12} {ra - sa:>9,.0f} {'':>8} {'':>6} {rb - sb:>10,.0f} "
          f"{'':>9} {'':>6} {(ra - sa) - (rb - sb):>+9,.0f}")


def demo():
    """Every commit attributes to a seat, and both seats trade."""
    run("pub_router.py", [1])
    assert sum(_rev[0].values()) > 0 and sum(_rev[1].values()) > 0, _rev
    assert sum(_spend[0].values()) > 0, _spend
    print("LEDGER_CHECKS_PASSED")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        opp, seeds = sys.argv[1], [int(a) for a in sys.argv[2:]] or [1]
        run(opp, seeds)
        report(len(seeds), 0, 1)
