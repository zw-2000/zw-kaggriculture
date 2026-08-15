"""Kaggriculture agent: the frontier template -- strawberry engine, small herd.

Rewritten against 35 measured top-10 seasons. The
previous agent was tuned on kaggle-environments 1.32.4; the competition runs
1.32.6, where the town centre buys **once a day at a flat rate** instead of
twice a day at up to 4x. That deleted subsidy was worth 8 units/product/day of
free demand, and every constant in the old agent was an answer to it. On the
real rules the old agent scored 17,098 mean where it had measured 54,224.

Three things follow from the demand model, and they are the whole strategy:

*Shops are the market now, and they are drawn with replacement.* Eight shop
instances, `MAX_SHOP_INSTANCES`, sampled from eight kinds -- so a season may run
YARN_STORE x3 and never unlock a BAKERY. Coverage is what matters: STRAWBERRY
appears in four of the eight kinds (BRUNCH_SPOT, ICE_CREAM_SHOP, SMOOTHIE_SHOP,
FARMERS_MARKET), the joint-widest in the game, and it is `ongoing` -- planted
once, watered, harvested four times. That is why every agent above 3000 rating
runs ~36 strawberry tiles, and why this one does.

*Melon has no shop demand at all.* Its only consumer is the town centre, so its
entire season sink is about 30 units. The old 14-tile melon "bootstrap" was
eating an 8/day subsidy that no longer exists. Melon is now what it actually is:
a two-burst cash crop, 5 tiles to fund the opening and 14 more on day 10, gone
by day 21.

*Animal product is capped by a much smaller drain, so the herd is small.* Milk
is linear x1.6 and wool quadratic x3.2 above target; with 1/day of town demand
the curves bite immediately. The frontier runs 13 animals -- 9 cows, 4 sheep --
and holds wool at $247. The old agent ran 20-27 and closed wool at $11. Geese
are simply dominated: 298 cows and 155 sheep across 35 top seasons, and **zero
geese**, because a goose is 2 eggs/day off a $50 base against a cow's 1.5 milk
off $160.

The opening is spent to the floor. $3,000 becomes five animals, ten seeds and
four hands in the first order block, and the farm runs on $9 for two days. A cow
bought on day 0 first yields on day 8; bought on day 6 it yields on day 14, and
on a 30-day clock that is a third of its output. There is no cash reserve
because there is no such thing as a rainy day inside 30 turns.

Land is a calendar -- quadrant 2 on day 6, quadrant 3 on day 10, quadrant 4
never (35 of 35 seasons, both days). The old utilization gate was correct *for
the old income model*: a farm with no strawberry cannot afford day-6 land, so
the gate never fired and the calendar starved it. With the strawberry ramp
behind it the calendar is affordable, which is the dependency the previous
round found and could not break.

The endgame needs no special case. Strawberry stops producing after four ticks
and the environment decays it to a weed on its own, so a strawberry reservation
that expires on day 12 converts the whole board to wheat between day 20 and day
26 by itself -- 57 wheat tiles at the frontier, 453 units sold, dumped on the
last day when stock in the shed is worth exactly $0.

Kept from the old agent because they are version-independent: tile roles handed
out as *ordered lists* nearest-shed-first (holding them in sets scattered the
pastures by tuple hash), fixed priority tiers rather than dollar-valued tasks
(deadlines drive this game -- feeding is worthless tomorrow), nearest-good-task
selection trading PRIO_WEIGHT steps per tier, and drip-feeding sells except when
the opponent's public board shows a dump coming.
"""
import math
from collections import Counter

CROPS = {  # mirrors kaggriculture.CROPS
    "WHEAT":      {"seed": 10, "first": 2, "maxday": 4,  "max_yield": 6, "interval": 0, "ongoing": False},
    "CARROT":     {"seed": 20, "first": 2, "maxday": 3,  "max_yield": 4, "interval": 0, "ongoing": False},
    "TOMATO":     {"seed": 50, "first": 8, "maxday": 8,  "max_yield": 4, "interval": 1, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first": 10, "maxday": 10, "max_yield": 4, "interval": 2, "ongoing": True},
    "MELON":      {"seed": 80, "first": 10, "maxday": 12, "max_yield": 6, "interval": 0, "ongoing": False},
}
ANIMALS = {  # mirrors kaggriculture.ANIMALS
    "GOOSE": {"cost": 300, "first": 4, "interval": 1, "product": "EGG",  "struct": "COOP"},
    "COW":   {"cost": 400, "first": 8, "interval": 2, "product": "MILK", "struct": "PASTURE"},
    "SHEEP": {"cost": 500, "first": 6, "interval": 3, "product": "WOOL", "struct": "PASTURE"},
}
# Fed and cared for every day, an animal yields (1 + interval)/interval per day:
# the CARE bonus banks +1 daily and pays out in full on the production tick.
RATE = {a: 1 + 1 / v["interval"] for a, v in ANIMALS.items()}
# Never buy a goose. 298 cows, 155 sheep and 0 geese across 35 top-10 seasons;
# total eggs sold by all of them, all season, was 12 units. Egg's log glut curve
# means it cannot be crashed, which is exactly why it is never worth much.
BUYABLE = ("COW", "SHEEP")
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER"]

I0 = 10000
MARKET_PARAMS = {  # mirrors kaggriculture.MARKET_PARAMS, animal products only
    "EGG":  {"base":  50, "T": 332, "below": ("linear", 0.40), "above": ("log",    0.20)},
    "MILK": {"base": 160, "T": 122, "below": ("sqrt",   0.60), "above": ("linear", 1.60)},
    "WOOL": {"base": 200, "T": 105, "below": ("log",    0.20), "above": ("sq",     3.20)},
}
SHOPS = {  # mirrors kaggriculture.SHOPS; single-product shops consume double
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}

# Refuse to sell below these prices: past them we're just donating stock to a
# market we flooded ourselves.
#
# Melon is deliberately absent, unlike the old agent. A floor is a bet the price
# recovers, and melon's only consumer is the town centre at 1 unit a day -- it
# recovers 1/day against a 14-tile harvest, i.e. never. The frontier crashes
# melon to $4 and takes the money. Fertilizer is absent for the same reason: no
# shop and not even the town centre consumes it.
SELL_FLOOR = {"MILK": 60, "WOOL": 60}
SHED_PRESSURE = 60      # units in a 100-slot shed past which the floors are
                        # ignored. See the sell block: a floor needs somewhere
                        # to wait, and a full shed is a farm that cannot bank
                        # anything it harvests.

# Orders clear one unit at a time down the price curve, so a 20-unit milk order
# walks $336 -> $294 against itself. There are 24 turns a day and the town
# refills scarcity between them: dribble it out instead.
SELL_CHUNK = {"EGG": 99, "WHEAT": 99}
SELL_CHUNK_DEFAULT = 5
RIVAL_DUMP = 20         # units standing unharvested on the opponent's board
                        # before we stop dribbling and clear ahead of theirs

DAYS = 30
LAND_PRICES = [1000, 2000, 4000]
LAND_DAYS = [6, 10]     # quadrant 2 on day 6, quadrant 3 on day 10, quadrant 4
                        # never -- 35 of 35 top seasons, both days, no exceptions.
                        # A calendar rather than a utilization gate: the gate is
                        # a proxy for "can we afford the next quadrant without
                        # starving the flock", and with strawberry income behind
                        # it the answer is yes on exactly these days. Copying the
                        # calendar *without* the strawberry ramp is what scored
                        # 5/48 in the previous round -- the schedule is
                        # downstream of the income model, not upstream of it.

HERD_CAP = 14           # frontier median is 13 animals. Milk is linear x1.6 and
                        # wool quadratic x3.2 above target, and the town now
                        # drains 1/product/day, so the curves bite immediately.
SHEEP_CAP = 4           # wool's quadratic cliff is the harshest in the game; the
                        # frontier ends on 4 sheep and 9 cows every time.
ANIMAL_TILES = 14       # ceiling on the pasture reservation; the live reserve
                        # tracks the herd we can actually stock (see `agent`)
WHEAT_FRACTION = 0.20   # of all owned tiles. Feed is bought, not grown, but
                        # home wheat is what carries a bad seed through a price
                        # spike -- and wheat is the endgame crop, so this is the
                        # floor, not the target: everything strawberry and melon
                        # give back lands here.
STRAW_TILES = 36        # the engine. 4 of 8 shop kinds want strawberry and it is
                        # `ongoing`: planted once, four production ticks, 4-8
                        # units a tile. Frontier sells 286 units a season at $247.
STRAW_STOP = 12         # last day a strawberry tile is reserved. Planted here it
                        # finishes its fourth tick on day 28; after that the
                        # reservation lapses and the tiles become wheat as the
                        # plants decay, which *is* the endgame conversion.
MELON_EARLY = 5         # wave 1: funds the opening, harvested day 10-12
MELON_LATE = 14         # wave 2 goes in on day 10, harvested day 20-22
MELON_WAVE2 = 10
MELON_STOP = 14         # after this a melon tile is a wheat tile

MAX_HANDS = 14          # hire cost is fib(n) *per day*, so the roster has to be
HANDS_EARLY = 4         # bought out of income. The frontier ramp is 4 hands on
HANDS_MID = 8           # day 0, 1-4 while broke, 6-7 from day 7, 8-14 from day
HANDS_DAY1 = 7          # 10 -- which is just "hire what today's cash allows".
HANDS_DAY2 = 10

CASH_RESERVE = 0        # the frontier opens $3,000 -> $9 and runs on $9 for two
                        # days. There is no rainy day inside 30 turns; every
                        # dollar not compounding by day 2 is a dollar wasted.
PRIO_WEIGHT = 14        # steps of walking traded per priority level
BUILD_PRIO = 6          # tier for BUILD_PASTURE -- the farm's only growth lever
PROJ_FRACTION = 0.5     # how far into the rest of the season to price an animal
PLANT_PRIO = 7          # tier for PLANT_*, endgame included -- see `_tasks`
WATER_PRIO = 3          # a plant that weeds over tonight, or produces tonight
FERT_PRIO = 5           # FERTILIZE doubles a production tick or a water bonus
PLANT_HOUR = 20         # `_new_plant` sets consecutive_unwatered = 1, so a crop
                        # must be watered the *same day* it goes in or it weeds
                        # over. Planting in the last three hours leaves no turns
                        # to get back to it -- and a strawberry seed is $100.
FEED_DAYS = 3           # only grow the flock while we can feed it this long
FERT_ONGOING_ONLY = 1   # 1 = fertilize strawberry only. A fertilized tick is
                        # worth ~$250 on strawberry and ~$50 on wheat, against a
                        # fertilizer that sells for ~$45-65 -- so on wheat the
                        # trade is roughly break-even before the walking.
FERT_CARRY = 2          # fertilizer a unit takes from the shed to spend on
                        # production ticks, and the amount it keeps rather than
                        # banking. 0 disables fertilizing altogether, since the
                        # only other source is whatever a unit is holding when it
                        # walks past a crop. Swept 1-8; 2 won, decaying to
                        # 33/120 by 8.
WHEAT_CARRY = 6         # one hand holding all the wheat is every hand behind it
                        # unable to FEED. Swept 3-50; 6 won 47/48.


QUADRANTS = ["NW", "NE", "SW", "SE"]   # block order for crops; NW is always owned


def _quadrant_of(x, y, half):
    return ("NE" if x >= half else "NW") if y < half else ("SE" if x >= half else "SW")


def _shed_tiles(n):
    h = n // 2
    return {(h - 1, h - 1), (h, h - 1), (h - 1, h), (h, h)}


def _roles(me, n, day, n_animal):
    """Assign every unlocked tile a role: an animal core, then crops in blocks.

    Two separate orderings, because the two halves of the farm are shaped by
    different costs.

    *Animals take the innermost tiles by distance*, the four shed-access tiles
    included. Those are not reserved ground -- `_is_shed_adjacent` only asks
    where a unit is standing, so a pasture built on one is fed by a unit that is
    simultaneously at the shed, at a walking cost of zero. The rank-1 farms all
    put a solid block of cows across the centre for exactly this reason.

    *Crops are blocked per quadrant, not by distance.* Sorting the whole board by
    distance from the shed hands each crop a **ring**, and a ring at radius 5 has
    an enormous perimeter: consecutive tiles in that order sit on opposite edges
    of the board, so a unit servicing one crop walks the circumference. Measured
    against the frontier, that ordering cost us a mean walk of 3.70 tiles before
    every productive action where they walk 1.19, and it is the whole difference
    between 43% of a season spent moving and 77%. Sorting by (quadrant, then
    distance) gives every crop a contiguous block instead, which is what the
    replays show: solid 5x1 and 5x3 slabs of melon, strawberry and wheat.

    Roles are handed out as *ordered lists*, not sets: `_tasks` walks them in
    order to spend a limited `build_budget`, so a set threw the ordering away and
    scattered the pastures over every tile we owned.

    Reservations expire, and the expiry is the plan: melon's lapses on day 14 and
    strawberry's on day 12, so as those plants are harvested or decay their tiles
    fall through to wheat. That is the whole endgame conversion, and it costs no
    code.
    """
    h = n // 2

    def dist(c):
        return abs(c[0] - h + 0.5) + abs(c[1] - h + 0.5)

    unlocked = set(me["unlocked_quadrants"])
    cells = [(x, y) for y in range(n) for x in range(n)
             if _quadrant_of(x, y, h) in unlocked]
    cells.sort(key=lambda c: (dist(c), c))
    animal, rest = cells[:n_animal], cells[n_animal:]
    # NW is always owned, so this ordering is stable however the land is bought.
    rest.sort(key=lambda c: (QUADRANTS.index(_quadrant_of(c[0], c[1], h)), dist(c), c))

    n_wheat = int(len(cells) * WHEAT_FRACTION)
    n_melon = (MELON_EARLY if day < MELON_WAVE2
               else MELON_LATE if day <= MELON_STOP else 0)
    # Never let the melon block crowd out the feed plot.
    n_melon = min(n_melon, max(0, len(rest) - n_wheat))
    melon = rest[len(rest) - n_melon:] if n_melon else []
    rest = rest[:len(rest) - n_melon]

    wheat, rest = rest[:n_wheat], rest[n_wheat:]
    straw = rest[:STRAW_TILES] if day <= STRAW_STOP else []
    # Anything strawberry does not claim -- and everything it gives back once the
    # reservation lapses -- is wheat.
    return {"ANIMAL": animal, "WHEAT": wheat + rest[len(straw):],
            "STRAWBERRY": straw, "MELON": melon}


def _shape(f, x):
    """The environment's price shape functions; log is ln(1+x) so f(0) = 0."""
    x = max(0.0, x)
    return (x * x if f == "sq" else math.sqrt(x) if f == "sqrt"
            else math.log1p(x) if f == "log" else x)


def _price_at(item, inv):
    """The environment's price curve evaluated at a hypothetical inventory."""
    p = MARKET_PARAMS[item]
    f, target = p["below"] if inv < I0 else p["above"]
    amp = target * p["base"] / _shape(f, p["T"])
    return max(1.0, p["base"] + (1 if inv < I0 else -1) * amp * _shape(f, abs(inv - I0)))


def _projected(inv, day, shops, farms):
    """What each animal product will fetch once the herds now standing on both
    boards have run their course.

    Today's price is the wrong number to buy on: a cow's milk does not reach the
    market for eight days, and on day 10 milk and wool both sit near base, so
    ranking on the spot price fills every pasture with one species before any
    feedback arrives.

    The drain term is the part that was wrong for a whole round. It used to read
    `per_shop * 6 + (4 if day >= 20 else 2 if day >= 10 else 1) * 2`, which is
    the town-centre demand *schedule that 1.32.6 deleted*, times the two ticks a
    day it no longer gets. The town centre now buys one of every non-fertilizer
    product once a day, flat, all season. Overstating it by up to 8 units/day
    meant the projected price never fell far enough for the buy order to rotate,
    so the old agent bought 20-27 animals and closed wool at $11.

    `shops` may list the same shop more than once -- 1.32.6 draws with
    replacement up to 8 instances -- and each copy consumes independently, so
    this counts instances rather than kinds on purpose.
    """
    horizon = max(1.0, (DAYS - day) * PROJ_FRACTION)  # mid-point of what's left
    out = {}
    for item in MARKET_PARAMS:
        per_shop = sum(2 if len(SHOPS[s]) == 1 else 1 for s in shops if item in SHOPS[s])
        drain = per_shop * 6 + 1          # 24/4 shop ticks a day; town centre 1/day
        supply = sum(RATE[t["animal"]] for f in farms for row in f["tiles"] for t in row
                     if isinstance(t, dict) and t.get("animal")
                     and ANIMALS[t["animal"]]["product"] == item)
        out[item] = _price_at(item, inv.get(item, I0) + (supply - drain) * horizon)
    return out


def _best_species(proj, day, money, n_sheep):
    """The animal whose product will still be worth something when ours lands.

    Self-balancing between cow and sheep: every cow raises projected milk supply
    and drops its projected price, rotating the buy order to wool until the
    marginal revenues meet. Geese are excluded outright -- see BUYABLE. Sheep are
    capped because wool is the only quadratic curve in the game, so the point
    where it stops being self-balancing and starts being self-destroying arrives
    faster than a projection at a half-season horizon can see.
    """
    ok = [a for a in BUYABLE
          if ANIMALS[a]["cost"] <= money and day + ANIMALS[a]["first"] < DAYS - 1
          and not (a == "SHEEP" and n_sheep >= SHEEP_CAP)]
    return max(ok, key=lambda a: RATE[a] * proj[ANIMALS[a]["product"]]) if ok else None


def _plant_tasks(t, x, y, day, out):
    """Water/fertilize/harvest for one standing crop.

    Ongoing and one-shot crops bank yield through completely different paths and
    the difference decides whether fertilizer pays:

    * A one-shot crop (wheat, melon) banks on `WATER`, immediately, and only
      inside `[(maxday+1)//2, maxday]`. Fertilizer makes that +2 instead of +1.
    * An ongoing crop (strawberry) banks at the end-of-day refresh, once every
      `interval` days from `first`, for at most `max_yield` ticks -- and the
      fertilizer bonus there requires the tile to have been *watered that day*.
      So a production day needs both, and both must land before the day ends.

    `yield_units` is capped at `max_yield` (4 for strawberry) while the tick
    counter is not, so an unharvested strawberry silently throws away the second
    half of every fertilized tick. Harvesting at 2 keeps the room open, which is
    the difference between 4 units a tile and the frontier's 8.
    """
    c = CROPS[t["crop"]]
    age = day - t["planted_day"]
    if c["ongoing"]:
        due = day + 1 - t["planted_day"] - c["first"]
        produces = (due >= 0 and c["interval"] and due % c["interval"] == 0
                    and due // c["interval"] + 1 <= c["max_yield"])
        if t["yield_units"] >= 2:
            out.append((1, x, y, "HARVEST"))       # keep room for a fertilized tick
        elif t["yield_units"] > 0:
            out.append((6, x, y, "HARVEST"))
        if not t["watered_today"] and (produces or t["consecutive_unwatered"] >= 1):
            out.append((WATER_PRIO, x, y, "WATER"))
        if produces and t["fertilized_until_day"] < day:
            out.append((FERT_PRIO, x, y, "FERTILIZE"))
        return
    window = (c["maxday"] + 1) // 2
    ripe = age >= c["first"] and t["yield_units"] > 0
    banking = window <= age <= c["maxday"] and t["yield_units"] < c["max_yield"]
    # Harvest the day it matures; sitting on it risks decay.
    if ripe and (age >= c["maxday"] or t["yield_units"] >= c["max_yield"]):
        out.append((1, x, y, "HARVEST"))
    elif not t["watered_today"]:
        if t["consecutive_unwatered"] >= 1:
            out.append((WATER_PRIO, x, y, "WATER"))   # dies tonight
        elif banking:
            out.append((5, x, y, "WATER"))            # +1 yield, or +2 fertilized
            # watering every other day is enough to survive, so we skip it
    elif ripe:
        out.append((7, x, y, "HARVEST"))
    if banking and t["fertilized_until_day"] < day and not FERT_ONGOING_ONLY:
        out.append((FERT_PRIO, x, y, "FERTILIZE"))


def _tasks(me, roles, day, hour, have_wheat, build_budget, build_op, build_prio):
    """(priority, x, y, op) for all outstanding work. Lower priority = sooner.

    These are fixed tiers rather than coin values on purpose. Pricing each task
    in dollars off live market prices is the more principled design and was
    tried -- it scored 17k against this version's 37.5k, because a $1,500 melon
    harvest reliably outbids a $250 FEED and the flock starves. Deadlines, not
    payoffs, drive this game: feeding is worthless tomorrow.

    `build_budget` caps how many empty structures we'll leave standing: an
    unstocked pasture is a dead tile, and an earlier version built 48 of them
    while too broke to buy a single animal.
    """
    out = []
    for (x, y), role in [(c, r) for r, cs in roles.items() for c in cs]:
        t = me["tiles"][y][x]
        if t == "LOCKED":
            continue
        if isinstance(t, dict) and "animal" in t:
            # Feeding is survival: two missed days and the animal is gone
            # forever. Except on the last day -- the final refresh that still
            # produces something sellable is day 28's, so day 29's feed is a
            # wheat bill against $0 of remaining output.
            if not t["fed_today"] and have_wheat and day < DAYS - 1:
                out.append((0 if t["consecutive_unfed"] >= 1 else 2, x, y, "FEED"))
            if t["yield_units"] >= 3:
                out.append((1, x, y, "HARVEST"))       # don't stall at max_held
            # One CARE on a cow is worth a whole $336 milk -- the single
            # highest-value action on the board. The bank pays out on the *next*
            # production, so a bonus banked on day 28 or later never lands.
            if not t["cared_today"] and t["fed_today"] and day < DAYS - 2:
                out.append((4, x, y, "CARE"))
            # ~$45 a unit, and the unit is already standing here, so it costs an
            # action and no walking. It is also the only source of the fertilizer
            # that doubles every strawberry tick.
            if t["fertilizer_available"]:
                out.append((5, x, y, "COLLECT_FERTILIZER"))
            if t["yield_units"] > 0:
                out.append((6, x, y, "HARVEST"))
            continue
        if isinstance(t, dict) and t.get("kind") == "PLANT":
            _plant_tasks(t, x, y, day, out)
            continue
        if isinstance(t, dict) and t.get("kind") == "WEED":
            # Was priority 8 and never reached: 15 weeds stood untouched from
            # day 15 to the end of the season, on land we wanted for pasture.
            # It matters more now -- every spent strawberry decays into one.
            out.append((7, x, y, "DIG"))
            continue
        # A coop takes only a goose and a pasture only a cow or sheep, so the
        # op carries the structure and the unit matches what it is carrying.
        if isinstance(t, dict) and t.get("kind") in ("PASTURE", "COOP"):
            # Above BUILD. A unit holding an animal beside an empty pasture that
            # walks off to build a *second* pasture instead has spent an action
            # to make the same problem twice.
            out.append((1, x, y, "PLACE_" + t["kind"]))  # skipped unless carrying one
            continue
        if t is None:
            if role == "ANIMAL" and build_budget > 0 and build_op:
                out.append((build_prio, x, y, build_op))
                build_budget -= 1
            elif hour > PLANT_HOUR:
                continue
            elif role == "MELON":
                out.append((PLANT_PRIO, x, y, "PLANT_MELON"))
            elif role == "STRAWBERRY":
                out.append((PLANT_PRIO, x, y, "PLANT_STRAWBERRY"))
            elif role == "WHEAT" and day <= DAYS - 3:  # wheat first-yields day 2
                # Planting stays the lowest tier all season, including the
                # endgame. Promoting it from day 25 -- on the theory that the
                # board is emptying and bare ground earns nothing -- measured
                # +33 games of 120 and was adopted. It was an artifact: it had
                # been measured while wheat was also being fertilized, and once
                # FERT_ONGOING_ONLY stopped that, promoting it *lost* 15-18 games
                # head-to-head on two disjoint seed sets. A late wheat plant pulls
                # a unit off a strawberry tick worth five times as much.
                out.append((PLANT_PRIO, x, y, "PLANT_WHEAT"))
    return out


def _step_toward(fx, fy, tx, ty):
    if fx < tx:
        return "EAST"
    if fx > tx:
        return "WEST"
    if fy < ty:
        return "SOUTH"
    return "NORTH"


def agent(obs):
    me = obs["farms"][obs["player"]]
    priv = obs["private"]
    n = len(me["tiles"])
    day, hour = obs["day"], obs["hour"]
    money = me["money"]
    prices = obs["market"]["prices"]
    shed = priv["shed"]
    invs = priv["inventories"]
    shed_tiles = _shed_tiles(n)

    units = [tuple(me["farmer"])] + [tuple(h) for h in me["hands"]]
    tiles = [t for row in me["tiles"] for t in row]
    dicts = [t for t in tiles if isinstance(t, dict)]
    n_animals = sum(1 for t in dicts if "animal" in t)
    n_sheep = sum(1 for t in dicts if t.get("animal") == "SHEEP")
    unfed = sum(1 for t in dicts if "animal" in t and not t["fed_today"])
    empty = Counter(t["kind"] for t in dicts
                    if t.get("kind") in ("PASTURE", "COOP") and "animal" not in t)
    n_struct = sum(empty.values())

    # Cash binds the flock, not actions and not tiles: feed is bought, not grown.
    # Never *grow* past what FEED_DAYS of wheat money supports -- a starved
    # animal is a total loss, and the whole flock starving by day 27 is how we
    # learned it. HERD_CAP is the other half: the market, not the farm, is the
    # ceiling.
    #
    # `pending` is the part that has to be exempt. The opening spends $3,000 down
    # to $53, so a purely forward-looking feed gate reads "cannot afford one more
    # animal" and therefore builds no pasture -- stranding five sheep we had
    # already bought in the shed for the whole first third of the season. The
    # gate throttles buying; it must never refuse to house stock already paid for.
    wheat_price = max(1, prices.get("WHEAT", 25))
    spendable = money - CASH_RESERVE
    # Animals bought but not yet standing on a tile. This has to count the ones
    # units are already carrying as well as the ones in the shed, or the opening
    # deadlocks: five sheep leave the shed on turn 2, `pending` reads 0, the
    # build budget it feeds goes to 0, no further pasture is ever built, and four
    # sheep ride around in unit inventories for the rest of the season.
    pending = sum(shed.get(a, 0) + sum(i.get(a, 0) for i in invs) for a in BUYABLE)
    capacity = min(HERD_CAP, n_animals + max(
        pending, int(max(0, spendable) // (wheat_price * FEED_DAYS))))

    proj = _projected(obs["market"]["inventory"], day,
                      obs["town"]["unlocked_shops"], obs["farms"])
    best = _best_species(proj, day, max(0, spendable), n_sheep)
    # Build for the animals we have already paid for as well as the ones we can
    # still afford. Sizing the budget off affordability alone deadlocks the
    # opening: the first order block spends $3,000 down to $53, so on the very
    # next turn nothing is affordable, `best` is None, no pasture is ever built,
    # and five sheep sit in the shed for eleven days with nowhere to stand.
    # Only cows and sheep are ever bought, so the structure is always a pasture.
    affordable = int(spendable // ANIMALS[best]["cost"]) + 1 if best else 0
    build_budget = max(0, min(capacity - n_animals - n_struct, pending + affordable))
    build_op = "BUILD_PASTURE"
    # The pasture reservation tracks the herd we can actually stock. Reserving a
    # flat 14 on day 0 would take 14 of the starting quadrant's 24 tiles away
    # from the melon and wheat that pay for the animals.
    n_animal = min(ANIMAL_TILES, n_animals + n_struct + build_budget)
    roles = _roles(me, n, day, n_animal)
    # A pasture is normally a growth lever and waits its turn behind the daily
    # chores -- raising it costs the flock, measured. But an animal already
    # bought and sitting in the shed is $400-500 earning nothing per day it has
    # nowhere to stand, and the opening buys five of them before a single
    # pasture exists. While any are waiting, housing them outranks everything.
    tasks = sorted(_tasks(me, roles, day, hour, any(i.get("WHEAT") for i in invs),
                          build_budget, build_op, 2 if pending else BUILD_PRIO))
    wanted = Counter(op for _, _, _, op in tasks)

    # ---------------- market ------------------------------------------------
    # Only 10 orders clear per turn and extras are silently dropped. Investments
    # are bursty and sells happen every one of the 24 turns in a day, so the
    # one-shot orders go first and sells take what slots are left.
    orders = []

    # 1. Feed. Non-negotiable at any price: two missed days and a $400 animal
    #    plus everything it would ever produce is gone.
    #
    #    Two things here are load-bearing, and each of them cost an entire
    #    opening herd before it was fixed. `herd` counts `pending`, because on
    #    the turn the opening buys its animals they are still in the shed, and
    #    waiting for them to be placed before buying their food starves all of
    #    them by day 2. And `feed_hold` is subtracted from everything spent
    #    below, because a reserve that the seed loop is free to spend is not a
    #    reserve: strawberry at $100 a tile drank $500 of it on turn one and left
    #    four sheep with a single wheat between them.
    herd = n_animals + pending
    wheat_stock = shed.get("WHEAT", 0) + sum(i.get("WHEAT", 0) for i in invs)
    pasture_room = max(0, empty["PASTURE"] + build_budget - pending)
    feed_hold = (max(0, min(capacity, herd + pasture_room) * FEED_DAYS - wheat_stock)
                 * wheat_price)
    if herd and day < DAYS - 1 and wheat_stock < herd + 10:
        room = 100 - sum(shed.values())
        buy = min(herd + 10 - wheat_stock, room, int(money // wheat_price))
        if buy > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", buy])
            feed_hold = max(0, feed_hold - buy * wheat_price)
    # Everything discretionary -- land, animals, seeds -- spends out of this.
    spendable = max(0, spendable - feed_hold)

    # 2. Labour, ramped. Hire cost is fib(n) *per day*, so a flat roster is a
    #    standing bill the opening cannot pay -- the frontier runs 4 hands while
    #    broke and 8-14 once strawberry lands. Split across the opening turns so
    #    a full roster doesn't eat the whole order budget at hour 0.
    cap = (HANDS_EARLY if day < HANDS_DAY1
           else HANDS_MID if day < HANDS_DAY2 else MAX_HANDS)
    if hour <= (cap - 1) // 6:
        for _ in range(min(6, max(0, cap - me["hires_today"]))):
            orders.append(["HIRE"])

    # 3. Land, on the calendar. See LAND_DAYS.
    n_extra = len(me["unlocked_quadrants"]) - 1
    if (n_extra < len(LAND_DAYS) and day >= LAND_DAYS[n_extra]
            and spendable >= LAND_PRICES[n_extra]):
        orders.append(["BUY_LAND"])
        spendable -= LAND_PRICES[n_extra]

    # 4. Stock. Unlike the old agent this does *not* wait for the pasture to
    #    exist -- it counts the ones this turn's `build_budget` is about to put
    #    up. Waiting cost us the entire day-0 herd: at hour 0 there are no
    #    structures, so the gate bought nothing, and a cow bought on day 6
    #    instead of day 0 loses a third of its season. Holding back the melon
    #    and wheat seed money keeps the bootstrap intact.
    #
    seed_hold = sum(CROPS[c]["seed"] * max(0, wanted["PLANT_" + c] - priv["seeds"].get(c, 0))
                    for c in ("WHEAT", "MELON"))
    room = pasture_room
    budget = max(0, spendable - seed_hold)
    grow = capacity - herd
    # Best first, then the next best with whatever is left -- the frontier's
    # opening is 4 sheep *and* a cow in one order block, and wool's quadratic
    # curve means the fifth sheep is worth much less than the first cow.
    for a in sorted(BUYABLE, key=lambda k: -RATE[k] * proj[ANIMALS[k]["product"]]):
        if day + ANIMALS[a]["first"] >= DAYS - 1:
            continue
        want = min(room, grow, int(budget // ANIMALS[a]["cost"]),
                   SHEEP_CAP - n_sheep if a == "SHEEP" else grow)
        if want > 0:
            orders.append(["BUY_ANIMAL", a, want])
            budget -= want * ANIMALS[a]["cost"]
            spendable -= want * ANIMALS[a]["cost"]
            room -= want
            grow -= want

    # 5. Seeds for whatever empty tiles we're about to plant, read straight off
    #    the task list so the planting cutoffs live in exactly one place. Order
    #    matters: wheat and melon are the bootstrap and are cheap, strawberry is
    #    $100 a tile and takes whatever is left. That ordering *is* the observed
    #    ramp -- the frontier buys 3 strawberry seeds on day 3 and 16 on day 10,
    #    not because of a schedule but because that is what the till held.
    for crop in ("WHEAT", "MELON", "STRAWBERRY"):
        short = wanted["PLANT_" + crop] - priv["seeds"].get(crop, 0)
        buy = max(0, min(short, int(spendable // CROPS[crop]["seed"])))
        if buy:
            orders.append(["BUY_SEED", crop, buy])
            spendable -= buy * CROPS[crop]["seed"]

    # 6. Sell, but never into a floor we created ourselves, and never faster
    #    than the curve recovers -- except at the end, where reward is money
    #    alone and stock still in the shed on the last tick is worth $0.
    dumping = day >= DAYS - 2
    # The opponent's whole board is public, unharvested `yield_units` included,
    # so their next dump is visible a day or more before it lands. Drip-feeding
    # assumes the curve recovers between our own orders, which it does -- but it
    # will not recover through someone else's harvest.
    rival = Counter()
    for row in obs["farms"][1 - obs["player"]]["tiles"]:
        for t in row:
            if not isinstance(t, dict) or not t.get("yield_units"):
                continue
            if t.get("animal"):
                rival[ANIMALS[t["animal"]]["product"]] += t["yield_units"]
            elif t.get("kind") == "PLANT":
                rival[t["crop"]] += t["yield_units"]
    # Wheat in the shed is feed, not stock. Selling it all and buying it back
    # next turn was the single largest market flow of the season.
    # A floor is a bet that the price recovers, and that bet needs somewhere to
    # wait. The shed holds 100. Measured on seed 137: milk and wool sat one
    # dollar under their floors from day 20, filled the shed by day 23, and then
    # blocked $300 strawberry from being deposited at all -- the season ended on
    # $48 with a hundred units dumped into a market at $1. Above SHED_PRESSURE
    # the floors come off: stock we cannot store is worth exactly nothing, and
    # the room it frees is worth whatever the best crop on the board fetches.
    crowded = sum(shed.values()) >= SHED_PRESSURE
    keep = {"WHEAT": 0 if day >= DAYS - 1 else n_animals + 10}
    sells = []
    for p in PRODUCTS:
        have = max(0, shed.get(p, 0) - keep.get(p, 0))
        q = (have if dumping or rival[p] >= RIVAL_DUMP
             else min(have, SELL_CHUNK.get(p, SELL_CHUNK_DEFAULT)))
        if q > 0 and prices.get(p, 0) >= (1 if dumping or crowded
                                          else SELL_FLOOR.get(p, 1)):
            sells.append((q * prices.get(p, 0), p, q))
    # Ten orders clear a turn and hiring can take six of them, so the slots that
    # are left have to go to the most valuable stock, not to whatever PRODUCTS
    # happens to list first.
    for _, p, q in sorted(sells, reverse=True):
        orders.append(["SELL", p, q])

    # ---------------- unit actions -----------------------------------------
    seeds = dict(priv["seeds"])
    stock = {a: shed.get(a, 0) for a in ANIMALS}
    # Local tallies, never `shed` itself: `obs` is the live observation and two
    # units in the same turn must not both be handed the last unit of stock.
    fert_left = shed.get("FERTILIZER", 0)
    claimed = set()
    acts = [None] * len(units)

    # Pass 1: shed work, which is unit-local. A unit standing on the shed banks
    # its load, restocks wheat, or collects an animal before anything else.
    for u, (ux, uy) in enumerate(units):
        inv = invs[u] if u < len(invs) else {}
        # Produce must reach the shed before it can be sold, but wheat, live
        # animals and fertilizer are working stock -- DROPping the lot and
        # re-PICKUPing it next turn is an infinite loop that once burned 962
        # actions a season. Fertilizer is held because the unit that collected it
        # is standing in the field where the crops that want it are.
        produce = {k: v for k, v in inv.items()
                   if k not in ("WHEAT", "FERTILIZER") and k not in ANIMALS and v > 0}
        n_produce = sum(produce.values())
        if (ux, uy) in shed_tiles:
            if n_produce and sum(shed.values()) < 100:
                item = max(produce, key=produce.get)
                acts[u] = ["PLACE", item, produce[item]]
            elif inv.get("FERTILIZER", 0) > FERT_CARRY and sum(shed.values()) < 100:
                acts[u] = ["PLACE", "FERTILIZER", inv["FERTILIZER"] - FERT_CARRY]
            elif unfed and inv.get("WHEAT", 0) == 0 and shed.get("WHEAT", 0) > 0:
                acts[u] = ["PICKUP", "WHEAT", min(WHEAT_CARRY, shed["WHEAT"])]
            if acts[u] is None and not any(inv.get(a) for a in ANIMALS):
                # Only fetch an animal there is somewhere to put. A cow carried
                # around with every pasture full leaves this unit permanently
                # "already carrying one" and so unable to fetch anything else.
                # Count the pastures this turn's build budget is about to put up
                # as well as the ones standing: on day 0 there are none standing,
                # so matching only against `empty` carried one sheep at a time
                # and left the other four in the shed for a week.
                room = max(empty["PASTURE"], min(build_budget, pending))
                a = max(ANIMALS, key=lambda k: min(
                    stock[k], room if ANIMALS[k]["struct"] == "PASTURE"
                    else empty[ANIMALS[k]["struct"]]))
                take = min(3, stock[a], room if ANIMALS[a]["struct"] == "PASTURE"
                           else empty[ANIMALS[a]["struct"]])
                if take:
                    acts[u] = ["PICKUP", a, take]
                    stock[a] -= take
            # Fertilizer is the only consumable a unit cannot obtain where it is
            # needed. COLLECT_FERTILIZER happens at a pasture and FERTILIZE
            # happens on a crop, so the only fertilizer in the field is whatever
            # a unit happened to be holding when it walked past -- which is why
            # ~26 FERTILIZE tasks a turn were emitted and ~118 were ever executed
            # in a whole season. Carrying a few out of the shed closes that loop.
            # It is a real trade, not free: fertilizer sells for ~$45-65 and the
            # tick it doubles is worth ~$250 on strawberry but only ~$50 on
            # wheat, so FERT_CARRY is swept rather than assumed.
            if (acts[u] is None and FERT_CARRY and not inv.get("FERTILIZER")
                    and wanted["FERTILIZE"] and fert_left > 0):
                take = min(FERT_CARRY, fert_left)
                acts[u] = ["PICKUP", "FERTILIZER", take]
                fert_left -= take
        # Hands hold everything until they walk it back; head home when loaded.
        elif n_produce >= 12:
            tx, ty = min(shed_tiles, key=lambda c: abs(c[0] - ux) + abs(c[1] - uy))
            acts[u] = [_step_toward(ux, uy, tx, ty)]

    # Pass 2: assign every remaining unit by cheapest (task, unit) pair over the
    # whole board at once, instead of letting each unit in turn grab its own
    # nearest task.
    #
    # Unit-at-a-time greedy looks equivalent and is not, because ties break by
    # *unit index* rather than by distance: the farmer claims the tile a hand is
    # already standing on, that hand re-targets, and next turn -- once everyone
    # has moved a step -- the assignment flips back. Measured on seed 7 that
    # thrash turned **9.9% of all our moves into direct reversals**, a unit
    # walking back the way it came, against 0.4% in the rank-1 replays. Every
    # reversal also strands the half-finished trip behind it, which is most of
    # why 74% of our season went on movement where the frontier spends 43%.
    #
    # Assigning globally makes the choice a function of positions alone, and
    # positions move one tile a turn, so the assignment is stable by
    # construction -- no per-unit target has to be carried between calls.
    #
    # Walking is still the dominant cost on a 10x10 board (a naive priority-only
    # sort burned 88% of a season on movement), so a priority level is still
    # worth PRIO_WEIGHT steps of detour.
    cand = []
    for pr, tx, ty, op in tasks:
        for u, (ux, uy) in enumerate(units):
            if acts[u] is not None:
                continue
            inv = invs[u] if u < len(invs) else {}
            if op == "FEED" and inv.get("WHEAT", 0) <= 0:
                continue
            if op == "FERTILIZE" and inv.get("FERTILIZER", 0) <= 0:
                continue
            if op.startswith("PLACE_") and not any(
                    inv.get(a) for a in ANIMALS if ANIMALS[a]["struct"] == op[6:]):
                continue
            if op.startswith("PLANT_") and seeds.get(op[6:], 0) <= 0:
                continue
            cand.append((pr * PRIO_WEIGHT + abs(tx - ux) + abs(ty - uy), u, tx, ty, op))
    cand.sort()

    for _, u, tx, ty, op in cand:
        if acts[u] is not None or (tx, ty) in claimed:
            continue
        # Re-check consumables: an earlier pair may have spent the last seed.
        if op.startswith("PLANT_") and seeds.get(op[6:], 0) <= 0:
            continue
        ux, uy = units[u]
        inv = invs[u] if u < len(invs) else {}
        claimed.add((tx, ty))
        if (ux, uy) != (tx, ty):
            acts[u] = [_step_toward(ux, uy, tx, ty)]
        elif op.startswith("PLACE_"):
            a = next(k for k in ANIMALS
                     if inv.get(k) and ANIMALS[k]["struct"] == op[6:])
            inv[a] -= 1
            acts[u] = ["PLACE", a]
        elif op.startswith("PLANT_"):
            seeds[op[6:]] -= 1
            acts[u] = ["PLANT", op[6:]]
        else:
            if op == "FEED":
                inv["WHEAT"] = inv.get("WHEAT", 0) - 1
            elif op == "FERTILIZE":
                inv["FERTILIZER"] = inv.get("FERTILIZER", 0) - 1
            acts[u] = [op]

    # Idle: stand still. Walking an idle unit home costs a move now and a move
    # back the instant work appears, and hands respawn at the shed every morning
    # anyway. Only a unit holding sellable produce has a reason to travel. The
    # frontier passes 15% of its turns; the old agent walked those turns instead.
    for u, (ux, uy) in enumerate(units):
        if acts[u] is not None:
            continue
        inv = invs[u] if u < len(invs) else {}
        carrying = sum(v for k, v in inv.items()
                       if k not in ("WHEAT", "FERTILIZER") and k not in ANIMALS and v > 0)
        if carrying and (ux, uy) not in shed_tiles:
            tx, ty = min(shed_tiles, key=lambda c: abs(c[0] - ux) + abs(c[1] - uy))
            acts[u] = [_step_toward(ux, uy, tx, ty)]
        else:
            acts[u] = ["PASS"]

    return {"farmer": acts[0], "hands": acts[1:], "market": orders[:10]}
