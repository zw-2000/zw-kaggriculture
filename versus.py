"""Compact head-to-head diff of one live replay: us versus the opponent.

    .venv/bin/python versus.py /tmp/kagg-replays/episode-106392212-replay.json

frontier.py's `analyze` writes the full per-day record, which is far too large to
read directly. This prints only the fields that have ever changed a decision:
actual units sold, unit-action mix (PASS is idle labour), the hiring ramp, and
the standing herd and crop mix at three checkpoints.

Sold and bought counts are *requested* quantities, not settled transactions: a
big round number usually means the opponent's constant for "all", and a same-day
wheat buy/sell round trip nets exactly zero (FINDINGS 11.7 and 15). Unit actions
are the executed record, so the PASS share and the action mix are the honest
comparison; read the market lines as intent only.
"""
import json
import sys
from collections import Counter

TEAM = "Zhian Wei"
CHECKPOINTS = (7, 15, 25)


def profile(steps, seat):
    sold, acts, seeds, bought = Counter(), Counter(), Counter(), Counter()
    hands, snaps = {}, {}
    for step in steps:
        state = step[seat]
        obs = state.get("observation") or {}
        if "farms" not in obs:
            continue
        day = obs["day"]
        me = obs["farms"][seat]
        action = state.get("action") or {}
        for op in action.get("market") or []:
            if op[0] == "SELL":
                sold[op[1]] += op[2] if len(op) > 2 else 1
            elif op[0] == "BUY_SEED":
                seeds[op[1]] += op[2] if len(op) > 2 else 1
            elif op[0] == "BUY_PRODUCT":
                bought[op[1]] += op[2] if len(op) > 2 else 1
        for unit in [action.get("farmer")] + (action.get("hands") or []):
            if unit:
                acts[unit[0]] += 1
        hands[day] = len(me["hands"])
        if obs["hour"] == 23:
            tiles = [t for row in me["tiles"] for t in row if isinstance(t, dict)]
            snaps[day] = {
                "money": int(me["money"]),
                "crops": dict(Counter(t["crop"] for t in tiles
                                      if t.get("kind") == "PLANT")),
                "animals": dict(Counter(t["animal"] for t in tiles if t.get("animal"))),
            }
    return {"sold": dict(sold.most_common()), "bought": dict(bought.most_common()),
            "seeds": dict(seeds.most_common()),
            "acts": dict(acts.most_common()), "hands": hands, "snaps": snaps}


def show(path):
    replay = json.load(open(path))
    names = replay["info"]["TeamNames"]
    mine = names.index(TEAM) if TEAM in names else 0
    for seat in (mine, 1 - mine):
        p = profile(replay["steps"], seat)
        tag = "US " if seat == mine else "OPP"
        final = replay["steps"][-1][seat].get("reward")
        print(f'{tag} {names[seat]} reward={final}')
        print(f'  sold   {p["sold"]}')
        print(f'  bought {p["bought"]}')
        print(f'  seeds  {p["seeds"]}')
        idle = p["acts"].get("PASS", 0)
        work = sum(v for k, v in p["acts"].items() if k != "PASS")
        print(f'  idle   PASS={idle} work={work} idle_share={idle / (idle + work):.1%}')
        print(f'  acts   ' + " ".join(f"{k}={v}" for k, v in p["acts"].items()
                                      if k not in ("PASS", "NORTH", "SOUTH", "EAST", "WEST")))
        print(f'  hands  ' + " ".join(f"d{d}:{p['hands'][d]}" for d in
                                      sorted(p["hands"]) if d % 5 == 0))
        for day in CHECKPOINTS:
            if day in p["snaps"]:
                s = p["snaps"][day]
                print(f'  d{day:<5} money={s["money"]} crops={s["crops"]} animals={s["animals"]}')


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for replay_path in sys.argv[1:]:
        print("##", replay_path.rsplit("/", 1)[-1])
        show(replay_path)
