"""How much produce do we lose to the shed's overflow discard?

    .venv/bin/python spill.py [opponent] [seeds...]

`_drop_inventories_to_shed` banks every carried item at day close and silently
DISCARDS anything past `shedCapacity` (kaggriculture.py:843). Nothing in main.py
watches that boundary -- `100 - sum(shed.values())` is read once, to size a wheat
purchase -- so a unit standing on a full shed at hour 23 loses its load and the
season simply scores lower with no trace in any profile.

This wraps the environment's own helper to count what it throws away, per item
and per day, for our seat. It changes no decision; the wrapper reports and then
calls through.

The top public write-up ("conserved route replay", the agent three of our live
opponents run) closes the day to 99 items rather than 100 for exactly this
reason, which is what prompted the measurement.
"""
import sys
from collections import Counter

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture import kaggriculture as K

import main

spill = Counter()
by_day = Counter()
_day = [0]
_orig = K._drop_inventories_to_shed


def _counting_drop(private, capacity):
    room = max(0, capacity - sum(private["shed"].values()))
    carried = Counter()
    for inv in private["inventories"]:
        carried.update({k: v for k, v in inv.items() if v > 0})
    lost = max(0, sum(carried.values()) - room)
    if lost:
        # Which items are lost depends on dict order, the same order the helper
        # itself walks, so attribute the loss to the tail of that walk.
        remaining = room
        for item, n in carried.items():
            take = min(n, remaining)
            remaining -= take
            if n - take:
                spill[item] += n - take
        by_day[_day[0]] += lost
    return _orig(private, capacity)


K._drop_inventories_to_shed = _counting_drop


def _wrap_end_of_day(orig):
    def inner(state, env, day):
        _day[0] = day
        return orig(state, env, day)
    return inner


K._end_of_day = _wrap_end_of_day(K._end_of_day)

if __name__ == "__main__":
    args = sys.argv[1:]
    opp = next((a for a in args if not a.isdigit()), "baseline.py")
    seeds = [int(a) for a in args if a.isdigit()] or [1, 3, 5, 7, 11]
    import importlib.util
    spec = importlib.util.spec_from_file_location("opp", opp)
    om = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(om)
    for s in seeds:
        spill.clear()
        by_day.clear()
        env = make("kaggriculture", configuration={"seed": s})
        env.run([main.agent, om.agent])
        # Both seats run through the same wrapper, so this is the pair's total.
        r = [st["reward"] for st in env.steps[-1]]
        print(f"seed {s:>4}  reward {r[0]:>9,.0f} vs {r[1]:>9,.0f}  "
              f"discarded(both seats) {sum(spill.values()):>4}  "
              f"{dict(spill.most_common(4))}")
        if by_day:
            print(f"           worst days {dict(by_day.most_common(3))}")
