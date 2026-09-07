"""Why do our units stand still? Classify every PASS against the work that was
outstanding at that moment.

    .venv/bin/python idle.py [opponent] [seed]

The live diff in FINDINGS 17 measured 851 PASS turns against Giba's 355 on the
same board. A PASS is only waste if work existed and something stopped the unit
taking it, so this separates the two cases:

  starved   a task was outstanding and every idle unit was filtered out of it,
            which for FEED, FERTILIZE, PLANT and PLACE means nobody was carrying
            the consumable the task needs
  empty     no task was outstanding at all

It reuses main._roles and main._tasks rather than restating them, so it cannot
drift from the agent. BUILD tasks are omitted (build_budget is a function of the
market block this does not re-run), which affects neither count.
"""
import sys
from collections import Counter

from kaggle_environments import make

import main

CONSUMABLE = {"FEED": "WHEAT", "FERTILIZE": "FERTILIZER"}


def blocked(op, invs, seeds_left):
    """Would every unit be filtered out of this op by main's consumable gates?"""
    item = CONSUMABLE.get(op)
    if item:
        return not any(i.get(item, 0) > 0 for i in invs)
    if op.startswith("PLACE_"):
        return not any(i.get(a) for i in invs for a in main.ANIMALS
                       if main.ANIMALS[a]["struct"] == op[6:])
    if op.startswith("PLANT_"):
        return seeds_left.get(op[6:], 0) <= 0
    return False


def season(opponent, seed):
    env = make("kaggriculture", configuration={"seed": seed}, debug=True)
    env.run([main.agent, opponent])
    passes = 0
    starved = Counter()
    empty_turns = 0
    surplus_tiles = 0
    surplus_turns = 0
    surplus_ops = Counter()
    for step in env.steps:
        state = step[0]
        obs = state.get("observation") or {}
        action = state.get("action") or {}
        if "farms" not in obs or not action:
            continue
        units = [action.get("farmer")] + (action.get("hands") or [])
        idle = sum(1 for u in units if u and u[0] == "PASS")
        if not idle:
            continue
        passes += idle
        me = obs["farms"][0]
        priv = obs["private"]
        invs = priv["inventories"]
        roles = main._roles(me, len(me["tiles"]), obs["day"],
                            sum(1 for row in me["tiles"] for t in row
                                if isinstance(t, dict) and "animal" in t))
        tasks = main._tasks(me, roles, obs["day"], obs["hour"],
                            any(i.get("WHEAT") for i in invs), 0, None, 9)
        if not tasks:
            empty_turns += idle
            continue
        # A unit only stands still when no (task, unit) pair survived, and pass 2
        # claims one *tile* per unit. So the honest surplus is distinct workable
        # tiles beyond what the working units could already have claimed.
        workable = {}
        for _pr, x, y, op in tasks:
            if blocked(op, invs, priv["seeds"]):
                starved[op] += 1
            else:
                workable.setdefault((x, y), op)
        surplus = len(workable) - (len(units) - idle)
        if surplus > 0:
            surplus_turns += 1
            surplus_tiles += surplus
            for op in list(workable.values())[:surplus]:
                surplus_ops[op] += 1
    return {"passes": passes, "idle_with_no_task": empty_turns,
            "starved_tasks": dict(starved.most_common()),
            "surplus_turns": surplus_turns, "surplus_tiles": surplus_tiles,
            "surplus_ops": dict(surplus_ops.most_common(6)),
            "reward": env.steps[-1][0]["reward"]}


if __name__ == "__main__":
    opp = sys.argv[1] if len(sys.argv) > 1 else "v27.py"
    seeds = [int(a) for a in sys.argv[2:]] or [7]
    for s in seeds:
        result = season(opp, s)
        print(f'seed {s}: ' + "  ".join(f"{k}={v}" for k, v in result.items()))
