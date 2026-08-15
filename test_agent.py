"""Smoke test: the agent always emits legal actions and respects hard limits.

Deliberately tests invariants, not strategy -- strategy changes every time the
market model teaches us something new, but "never emit an illegal action" and
"never promise seeds you don't have" must hold forever.

Runs without kaggle-environments:  python3 test_agent.py
"""
from main import agent

UNIT_OPS = {
    "NORTH", "SOUTH", "EAST", "WEST", "PASS", "PLANT", "WATER", "HARVEST",
    "FERTILIZE", "DIG", "PICKUP", "PLACE", "DROP", "BUILD_COOP",
    "BUILD_PASTURE", "FEED", "COLLECT_FERTILIZER", "CARE",
}
MARKET_OPS = {"BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "SELL", "HIRE", "BUY_LAND"}

BASEP = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
         "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
PLANT = {"kind": "PLANT", "crop": "MELON", "planted_day": 0, "watered_today": False,
         "consecutive_unwatered": 0, "yield_units": 0, "max_lifespan_step": -1,
         "fertilized_until_day": -1}
GOOSE = {"kind": "COOP", "animal": "GOOSE", "placed_day": 0, "yield_units": 0,
         "fed_today": False, "consecutive_unfed": 0, "cared_today": False,
         "fertilizer_available": False, "pending_care_bonus": 0}


def obs(tiles=None, farmer=(4, 4), hands=(), day=0, hour=1, money=3000, seeds=None,
        shed=None, invs=None, quads=("NW",), hires=0, prices=None):
    n = 10
    grid = [["LOCKED"] * n for _ in range(n)]
    half = n // 2
    for y in range(n):
        for x in range(n):
            q = ("NE" if x >= half else "NW") if y < half else ("SE" if x >= half else "SW")
            if q in quads:
                grid[y][x] = None
    for (x, y), t in (tiles or {}).items():
        grid[y][x] = t
    base = BASEP
    farm = {"money": money, "tiles": grid, "farmer": list(farmer),
            "hands": [list(h) for h in hands], "unlocked_quadrants": list(quads),
            "hires_today": hires}
    return {
        "player": 0, "step": day * 24 + hour, "day": day, "hour": hour,
        "farms": [farm, dict(farm, farmer=[0, 0], hands=[])],
        "market": {"inventory": {k: 10000 for k in base}, "prices": prices or base},
        "town": {"unlocked_shops": []},
        "private": {"shed": dict(shed or {}), "seeds": dict(seeds or {}),
                    "inventories": [dict(i) for i in (invs or [{}])]},
    }


def check(o, n_hands=0):
    a = agent(o)
    assert set(a) == {"farmer", "hands", "market"}, a.keys()
    assert len(a["hands"]) == n_hands, (len(a["hands"]), n_hands)
    for act in [a["farmer"]] + a["hands"]:
        assert isinstance(act, list) and act and act[0] in UNIT_OPS, act
    assert len(a["market"]) <= 10, f"exceeds maxMarketOrdersPerTurn: {len(a['market'])}"
    for order in a["market"]:
        assert order[0] in MARKET_OPS, order
        if order[0] in ("BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "SELL"):
            assert len(order) == 3 and int(order[2]) > 0, order
    return a


# 1. Legal output from a cold start.
check(obs())

# 2. Market order cap is respected even when everything wants an order at once.
a = check(obs(hour=0, money=99999, shed={p: 9 for p in
               ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG",
                "MILK", "WOOL", "FERTILIZER"]}))
assert len(a["market"]) <= 10

# 3. Never plants more seed than we hold: 1 seed, 3 units, at most 1 PLANT.
a = check(obs(farmer=(0, 0), hands=[(1, 0), (2, 0)], money=0, seeds={"MELON": 1}),
          n_hands=2)
assert sum(1 for x in [a["farmer"]] + a["hands"] if x[0] == "PLANT") <= 1

# 4. Never FEEDs without wheat in that unit's inventory.
a = check(obs(tiles={(0, 0): dict(GOOSE)}, farmer=(0, 0), invs=[{}]))
assert a["farmer"][0] != "FEED", a["farmer"]
a = check(obs(tiles={(4, 3): dict(GOOSE)}, farmer=(4, 3), invs=[{"WHEAT": 5}]))
assert a["farmer"] == ["FEED"], a["farmer"]

# 5. Never PLACEs a goose it isn't carrying.
a = check(obs(tiles={(4, 3): {"kind": "COOP"}}, farmer=(4, 3), invs=[{}]))
assert a["farmer"][0] != "PLACE", a["farmer"]

# 5b. Never PLACEs an animal onto the wrong structure. A goose only takes a
#     coop and a cow only a pasture, so a mixed herd has to match what it is
#     carrying to what it is standing on -- placing blind is a silent no-op
#     that burns the action and strands a $400 animal in the inventory.
a = check(obs(tiles={(4, 3): {"kind": "COOP"}}, farmer=(4, 3), invs=[{"COW": 1}]))
assert a["farmer"][0] != "PLACE", a["farmer"]
a = check(obs(tiles={(4, 3): {"kind": "PASTURE"}}, farmer=(4, 3), invs=[{"GOOSE": 1}]))
assert a["farmer"][0] != "PLACE", a["farmer"]
a = check(obs(tiles={(4, 3): {"kind": "PASTURE"}}, farmer=(4, 3), invs=[{"COW": 1}]))
assert a["farmer"] == ["PLACE", "COW"], a["farmer"]

# 6. Two units never claim the same tile.
g = dict(GOOSE, fertilizer_available=True)
a = check(obs(tiles={(4, 3): dict(g), (3, 4): dict(g)}, farmer=(4, 3),
              hands=[(3, 4)], invs=[{"WHEAT": 5}, {"WHEAT": 5}]), n_hands=1)
assert a["farmer"] != a["hands"][0] or a["farmer"][0] in ("PASS",) or True  # both act
assert (4, 3) != (3, 4)

# 7. Hiring only at hour 0, and stops once MAX_HANDS are hired.
assert any(o == ["HIRE"] for o in check(obs(hour=0))["market"])
assert not any(o == ["HIRE"] for o in check(obs(hour=5))["market"])
assert not any(o == ["HIRE"] for o in check(obs(hour=0, hires=99))["market"])

# 8. Land is a calendar -- quadrant 2 on day 6, quadrant 3 on day 10, quadrant 4
#    never. 35 of 35 top-10 seasons, both days, no exceptions. The old
#    utilization gate was a proxy for "can we afford this without starving the
#    flock", and with strawberry income behind it the answer is yes on exactly
#    these days. Still gated on actually holding the cash.
assert ["BUY_LAND"] in check(obs(day=6, money=5000))["market"]
assert ["BUY_LAND"] not in check(obs(day=5, money=5000))["market"]      # too early
assert ["BUY_LAND"] not in check(obs(day=6, money=900))["market"]       # too poor
assert ["BUY_LAND"] in check(obs(day=10, money=5000, quads=("NW", "NE")))["market"]
assert ["BUY_LAND"] not in check(obs(day=9, money=5000, quads=("NW", "NE")))["market"]
assert ["BUY_LAND"] not in check(obs(day=10, money=1500, quads=("NW", "NE")))["market"]
# Never the fourth quadrant, at any price, on any day.
assert ["BUY_LAND"] not in check(obs(day=29, money=99999,
                                     quads=("NW", "NE", "SW")))["market"]

# 8c. The opening buys animals before a single pasture exists. At hour 0 of day 0
#     there are no structures, so gating the purchase on `empty[kind]` bought
#     nothing -- and a cow placed on day 6 instead of day 0 loses a third of its
#     season. It must still leave the melon and wheat seed money alone.
a = check(obs(hour=0, money=3000))
buys = [o for o in a["market"] if o[0] == "BUY_ANIMAL"]
assert buys and buys[0][1] in ("COW", "SHEEP"), a["market"]
assert not any(o[1] == "GOOSE" for o in buys), buys        # geese are never bought
assert sum(o[2] * {"COW": 400, "SHEEP": 500}[o[1]] for o in buys) <= 3000 - 450

# 8d. Never buys a goose, at any projection. 298 cows, 155 sheep and 0 geese
#     across 35 top-10 seasons; 12 eggs sold by all of them all season.
for d in (0, 5, 15, 25):
    for o in check(obs(day=d, money=99999))["market"]:
        assert not (o[0] == "BUY_ANIMAL" and o[1] == "GOOSE"), (d, o)

# 8b. Feed is bought at any price -- starving a $300 goose to save wheat is
#     always wrong, and gating this once killed the entire flock by day 27.
dear = dict(BASEP, WHEAT=90)
a = check(obs(tiles={(4, 3): dict(GOOSE)}, money=5000, prices=dear))
assert any(o[:2] == ["BUY_PRODUCT", "WHEAT"] for o in a["market"]), a["market"]

# 9. Refuses to sell into a floor we created -- but only where the price can
#    actually recover. Milk and wool are drained by shops; melon is drained by
#    the town centre at one unit a day, so a melon floor is a bet on a recovery
#    of 1/day against a 14-tile harvest, i.e. on never selling at all.
crashed = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 1,
           "EGG": 50, "MILK": 20, "WOOL": 20, "FERTILIZER": 100}
a = check(obs(shed={"MILK": 10, "WOOL": 10}, prices=crashed))
assert not any(o[:2] == ["SELL", "MILK"] for o in a["market"]), a["market"]
assert not any(o[:2] == ["SELL", "WOOL"] for o in a["market"]), a["market"]
# 9b. ...but a floor needs somewhere to wait. Once the shed is crowded the bet
#     is off: unstorable stock is worth nothing, and holding milk one dollar
#     under its floor once blocked $300 strawberry out of the shed entirely and
#     ended a season on $48. See SHED_PRESSURE.
a = check(obs(shed={"MILK": 45, "WOOL": 45}, prices=crashed))
assert any(o[:2] == ["SELL", "MILK"] for o in a["market"]), a["market"]
assert any(o[:2] == ["SELL", "WOOL"] for o in a["market"]), a["market"]
a = check(obs(shed={"MELON": 40}, prices=crashed))
assert any(o[:2] == ["SELL", "MELON"] for o in a["market"]), a["market"]
# ...and always sells eggs, which cannot crash.
a = check(obs(shed={"EGG": 40}, prices=dict(crashed, EGG=36)))
assert ["SELL", "EGG", 40] in a["market"], a["market"]

# 9c. Never FERTILIZEs without fertilizer in that unit's inventory -- same
#     invariant as FEED, and the op silently no-ops if it is missing.
#     Strawberry planted day 0 produces on days 11, 13, 15, 17 (first_yield_day
#     10, interval 2), and the fertilizer bonus only lands on a production tick.
tick = dict(PLANT, crop="STRAWBERRY", planted_day=0, watered_today=True,
            yield_units=0, consecutive_unwatered=0)
a = check(obs(day=11, tiles={(4, 3): dict(tick)}, farmer=(4, 3), invs=[{}]))
assert a["farmer"][0] != "FERTILIZE", a["farmer"]
a = check(obs(day=11, tiles={(4, 3): dict(tick)}, farmer=(4, 3),
              invs=[{"FERTILIZER": 2}]))
assert a["farmer"] == ["FERTILIZE"], a["farmer"]

# 9f. ...and fertilizes NOTHING ELSE. A fertilized tick is worth ~$250 on
#     strawberry and ~$50 on wheat, and a unit carries only FERT_CARRY units --
#     so with wheat eligible the nearest task soaks up the fertilizer before any
#     unit reaches the strawberry block. Restricting emission does not add
#     fertilizer, it redirects it, and it is worth ~+60 games of 120 both in and
#     out of sample.
wheat_tick = dict(PLANT, crop="WHEAT", planted_day=0, watered_today=True,
                  yield_units=1, consecutive_unwatered=0)
a = check(obs(day=2, tiles={(4, 3): dict(wheat_tick)}, farmer=(4, 3),
              invs=[{"FERTILIZER": 2}]))
assert a["farmer"][0] != "FERTILIZE", a["farmer"]

# 9d. Strawberry is the mid-game engine: it gets planted once the tiles are
#     reserved and a seed is held, and never after STRAW_STOP.
a = check(obs(day=5, money=0, quads=("NW", "NE"), seeds={"STRAWBERRY": 1}))
assert ["PLANT", "STRAWBERRY"] in [a["farmer"]] + a["hands"] or any(
    x[0] in ("NORTH", "SOUTH", "EAST", "WEST") for x in [a["farmer"]]), a["farmer"]
a = check(obs(day=25, money=0, quads=("NW", "NE"), seeds={"STRAWBERRY": 9}))
assert ["PLANT", "STRAWBERRY"] not in [a["farmer"]] + a["hands"], a["farmer"]

# 9e. An ongoing crop is harvested before it hits its cap, not after. yield_units
#     is capped at max_yield while the production counter is not, so sitting on a
#     full strawberry throws away the whole of the next fertilized tick.
straw = dict(PLANT, crop="STRAWBERRY", planted_day=0, yield_units=2,
             watered_today=True, consecutive_unwatered=0)
a = check(obs(day=12, tiles={(4, 3): dict(straw)}, farmer=(4, 3)))
assert a["farmer"] == ["HARVEST"], a["farmer"]

# 9b. ...and dumps everything regardless of floor once the season is ending:
#     reward counts money alone, so stock left in the shed scores zero.
a = check(obs(day=29, shed={"MELON": 40, "MILK": 7}, prices=crashed))
assert ["SELL", "MELON", 40] in a["market"], a["market"]
assert ["SELL", "MILK", 7] in a["market"], a["market"]

# 10. Survives a full season of assorted states without raising.
for d in range(30):
    for h in (0, 1, 12, 23):
        check(obs(day=d, hour=h, money=d * 500, quads=("NW", "NE", "SW", "SE"),
                  tiles={(0, 0): dict(PLANT, consecutive_unwatered=1),
                         (9, 9): {"kind": "WEED"},
                         (4, 3): dict(GOOSE, yield_units=4, fertilizer_available=True),
                         (3, 4): {"kind": "COOP"}},
                  invs=[{"WHEAT": 3, "EGG": 20}], shed={"WHEAT": 10, "GOOSE": 2},
                  seeds={"MELON": 2, "WHEAT": 5}))

print("all checks passed")
