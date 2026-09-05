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
leads with strawberry, and why here it takes every tile the animal, melon and
wheat carves leave it -- at most 36, and 28 once melon's second wave lands.
STRAW_TILES is that ceiling, not a target; see its comment.

*Melon has no shop demand at all.* Its only consumer is the town centre, so its
entire season sink is about 30 units. The old 14-tile melon "bootstrap" was
eating an 8/day subsidy that no longer exists. Melon is now what it actually is:
a two-burst cash crop, 12 tiles to fund the opening and a 14-tile second wave on
day 10, with the reservation lapsing after day 12 so the ground falls through to
wheat.

*Animal product is capped by a much smaller drain, so the herd is small.* Milk
is linear x1.6 and wool quadratic x3.2 above target; with 1/day of town demand
the curves bite immediately. The frontier runs 13 animals -- 9 cows, 4 sheep --
and holds wool at $247. The old agent ran 20-27 and closed wool at $11. Geese
are simply dominated: 298 cows and 155 sheep across 35 top seasons, and **zero
geese**, because a goose is 2 eggs/day off a $50 base against a cow's 1.5 milk
off $160.

The opening is spent to the floor. $3,000 becomes 3 animals, 18 seeds and 4
hands in the first order block -- 4 animals and 19 seeds by the end of day 0 --
and the farm closes days 0 and 1 on $23 and $16. A cow
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
(deadlines drive this game -- feeding is worthless tomorrow), and nearest-good-task
selection trading PRIO_WEIGHT steps per tier.

*Selling is unconditional, and that is the newest and least intuitive result.*
The agent used to ration its sells four ways -- price floors, a shed-pressure
release for them, a per-turn drip chunk, and a trigger that cleared stock ahead
of the opponent's visible dump. Each was swept and each lost, all converging on
the same margin. Orders clear one unit at a time *alternating between the two
players*, so anything held back is the good part of the price curve left standing
for the opponent to take. The same logic walked HERD_CAP down 14 -> 12 -> 10: a
14-animal herd closes milk at $7 where 12 holds $135, and 10 wins again on top
of that. Both changes make our farm *poorer* in a
mirror match and win head-to-head, because the leaderboard pays for market share
rather than for farm income -- so a mirror match, or any solo-optimality
argument, will reject exactly the changes that win. Measure head-to-head.
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
MARKET_PARAMS = {  # mirrors kaggriculture.MARKET_PARAMS (1.32.7), every product
    # The crops are here because `_projected` now has to price TOMATO. They carry
    # no supply term -- `_projected` only knows how to count animals -- so a crop
    # entry projects pure town drain, which is exactly the question the tomato
    # block asks: how far below target will this be when our first tick lands.
    "WHEAT":      {"base":  25, "T": 400, "below": ("sqrt",   0.80), "above": ("log",    0.20)},
    "CARROT":     {"base":  35, "T": 450, "below": ("hinge",  1.00), "above": ("sqrt",   0.70)},
    "TOMATO":     {"base":  60, "T": 200, "below": ("hinge",  0.40), "above": ("sqrt",   0.60)},
    "STRAWBERRY": {"base": 120, "T": 100, "below": ("sqrt",   0.70), "above": ("linear", 1.60)},
    "MELON":      {"base": 250, "T": 300, "below": ("log",    0.20), "above": ("sq",     3.60)},
    "EGG":  {"base":  50, "T": 332, "below": ("hinge",  0.40), "above": ("log",    0.20)},
    "MILK": {"base": 160, "T": 122, "below": ("sqrt",   0.60), "above": ("linear", 1.60)},
    "WOOL": {"base": 200, "T": 105, "below": ("log",    0.20), "above": ("sq",     3.20)},
}
HINGE_GAIN = 8.0        # mirrors kaggriculture.HINGE_GAIN
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

# There are no sell restraints, and that is a measured result rather than an
# omission. Price floors on milk and wool, a shed-pressure release for them, a
# per-turn drip-feed chunk and a sell-ahead-of-the-rival trigger all used to live
# here; each was swept against a frozen copy of this agent and each lost, all of
# them converging on the same ~87/120. See the sell block in `agent` and
# FINDINGS 10.11 and 10.16. The one thing still held back is feed wheat, which is
# not a market judgement at all.

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
LAND_DAY4 = 99          # day the fourth quadrant unlocks; anything > DAYS means
                        # never, which is the frontier's choice in 35 of 35
                        # seasons. Read at call time rather than folded into
                        # LAND_DAYS so it can actually be swept -- the frontier
                        # is strawberry-led, and WHEAT_FRACTION=0.32 changed what
                        # land is *for*: wheat's log glut curve turns acreage
                        # into volume that does not crash its own price.

HERD_CAP = 13           # was 10, and the 10 was not wrong so much as starved.
                        # Every earlier herd measurement was taken at
                        # FEED_DAYS=4, which reserved feed money before animals
                        # could be bought -- so the cap was never the binding
                        # constraint, the cash was, and raising it only cost
                        # tiles. 16 scored 37/120 under that setting. With
                        # FEED_DAYS=3 the same family re-measures at 13 -> 80/120
                        # in-sample and 72/120 out of sample (12 and 14 both 69,
                        # so a plateau rather than a spike; 16 still only 57).
                        # Controls landed on exactly 60 in both runs.
                        # This is also the frontier's own number -- FINDINGS
                        # 10.x recorded "the frontier runs 13" and judged it
                        # non-transferable, on a benchmark that could not afford
                        # to fill the pasture.
                        # milk is linear x1.6 and wool quadratic x3.2 above
                        # target, and the town drains only 1/product/day, so the
                        # curves bite immediately. 14 was still gluting: it closes
                        # milk at $7 where 12 holds $135. Two effects, and they
                        # stack -- every animal costs a FEED, a CARE and a
                        # COLLECT_FERTILIZER every single day, so two fewer
                        # returns ~120 actions a season straight into crop work
                        # (PLANT 126 -> 153, WATER 574 -> 640), and we stop
                        # crashing the market with the harshest curve in the game.
                        # 14 -> 12 won 87/120 on that argument alone. Then the
                        # sell block lost its restraints and wheat took a third
                        # of the board, which repriced the herd again: 12 -> 10
                        # is a further 80/120 in-sample and 93/120 out-of-sample.
                        # 8 is too few (41/120) and 14 is worth 70/120 in-sample
                        # but only 46 out-of-sample, i.e. noise. The frontier
                        # runs 13, but the frontier also rations its sells.
SHEEP_CAP = 6           # was 4, and the 4 was a HERD_CAP=10 answer to a question
                        # that changed when the herd went to 13. Three extra
                        # animals have to go somewhere, and wool is where.
                        #   in-sample      5 -> 68   6 -> 72   8 -> 69  (ctrl 60)
                        #   out-of-sample  5 -> 68   6 -> 74   7 -> 76  (ctrl 60)
                        # 6 is taken over 7 because 6 has both readings and they
                        # agree (72/74); 7 has only the out-of-sample.
                        # This overturns a *live* result, which is the part worth
                        # remembering: variant_sheep8 spent a real submission slot
                        # and hours of episodes establishing SHEEP_CAP=8 was bad.
                        # It was bad given ten animals. Live evidence costs more
                        # than local evidence and is no less conditional on the
                        # configuration it was gathered in.
                        # wool's quadratic cliff is the harshest in the game; the
                        # frontier ends on 4 sheep and 9 cows every time.
ANIMAL_TILES = 14       # ceiling on the pasture reservation; the live reserve
                        # tracks the herd we can actually stock (see `agent`)
WHEAT_FRACTION = 0.38   # Re-swept under HERD_CAP=13 and both sides of 0.38 this
                        # time -- the earlier sweep went upward only (0.38/0.44/
                        # 0.50), got a clean monotone decline and concluded wheat
                        # acreage was already right. A one-sided sweep can only
                        # show the current value beats the side you tested.
                        #   in-sample  .24 76  .28 20  .32 80  .35 60  .44 14
                        #   out-of-s.  .28 24  .32 62  .35 69          (ctrl 60)
                        # 0.32's 80 did not replicate -- 62 on fresh seeds is +2
                        # over the null, the overfit signature this file records
                        # at 13.6. Not adopted; 0.38 stands.
                        # The crater at 0.28 is real -- 20 and 24 across two
                        # disjoint seed sets, between neighbours at 76 and 80 --
                        # and it is NOT a layout discontinuity. That was the first
                        # guess and it is refuted: `_roles` is smooth across the
                        # whole range. At three quadrants wheat goes 18/21/24/26/
                        # 28 and strawberry 32/29/26/24/22, monotone, no jump.
                        # So a smooth input produces a smooth board and a
                        # catastrophic result, and the mechanism is unexplained.
                        # Note the rest of this surface is noisy -- 0.32 scored
                        # 80 in-sample and 62 out -- so treat any single reading
                        # here as unreliable and only 0.28's badness as solid.
                        # of all owned tiles. Feed is bought, not grown, but
                        # home wheat is what carries a bad seed through a price
                        # spike -- and wheat is the endgame crop, so this is the
                        # floor, not the target: everything strawberry and melon
                        # give back lands here.
                        #
                        # Re-swept after the sell block dropped its restraints,
                        # and it moved 0.26 -> 0.32 for 119/120 in-sample and
                        # 120/120 out-of-sample, seats 60/60. Wheat is the only
                        # product in the game with a *log* glut curve: dumping a
                        # full throughput unit past equilibrium takes it from $25
                        # to $20, and two units to $19. Strawberry and milk are
                        # linear x1.6, wool sq x3.2, melon sq x3.6 -- all of them
                        # reach the $1 floor on a modest glut. Once we sell
                        # everything we harvest the moment we harvest it, growing
                        # a crashable crop means crashing it ourselves, so the
                        # mix shifts to the one thing the market can absorb.
                        # Re-swept again after MELON_EARLY went to 12 and moved
                        # 0.32 -> 0.38 (88/120 in-sample, 91/120 out-of-sample).
                        #
                        # !! DO NOT RAISE THIS. 0.41 scores 1/120 in-sample and
                        # **0/120** out-of-sample, two tiles from the adopted
                        # value. The obvious explanation is wrong and was tested:
                        # `_roles` carves wheat before melon and clamps melon to
                        # the remainder, so raising this looks like it starves the
                        # 120/120 opening melon block. Re-ordering the carve so
                        # melon takes its tiles first measured **neutral** (62/120)
                        # and the cliff did not move -- 0.44 -> 6/120, 0.50 ->
                        # 0/120 with melon fully protected. The ceiling is real:
                        # past ~0.38 wheat is simply displacing crops worth more,
                        # whichever one the carve order makes pay for it.
                        # Re-sweep after any change to MELON_EARLY or HERD_CAP.
                        # See FINDINGS 10.18 / 10.24 / 10.27.
STRAW_TILES = 36        # REVERTED to the v17 value. This scored 134/240 against its
                        # immediate predecessor and confirmed out of sample, and
                        # it still LOSES ground against the frozen v17 reference:
                        # with all four of this round's late adoptions in, the
                        # agent scored 58/120 against v17 where it had scored
                        # 101/120 eight adoptions earlier. Reverting all four
                        # restores exactly 101-19-0. See LINEAGE at the head of
                        # the settled-constants block.
STRAW_STOP = 12         # last day a strawberry tile is reserved. Planted here it
                        # finishes its fourth tick on day 28; after that the
                        # reservation lapses and the tiles become wheat as the
                        # plants decay, which *is* the endgame conversion.
MELON_EARLY = 12        # REVERTED to the v17 value. This scored 177/240 against its
                        # immediate predecessor and confirmed out of sample, and
                        # it still LOSES ground against the frozen v17 reference:
                        # with all four of this round's late adoptions in, the
                        # agent scored 58/120 against v17 where it had scored
                        # 101/120 eight adoptions earlier. Reverting all four
                        # restores exactly 101-19-0. See LINEAGE at the head of
                        # the settled-constants block.
MELON_LATE = 0          # NO second melon wave. The tiles fall through to
                        # strawberry, which is what the frontier does: it runs
                        # 14 melon and 33-36 strawberry on days 11-19 where we
                        # ran 22-29 melon and 17 strawberry.
                        # 108/120 in-sample and 114/120 out-of-sample (114W-6L,
                        # seats 58/56) against a 60/120 control; 6 -> 108/108,
                        # 10 -> 104. Mean 91,904 against the control's 83,590.
                        #
                        # FINDINGS 3 lists this under "Refuted mechanisms -- do
                        # not re-open": MELON_LATE=0 scored **2/120** and the
                        # conclusion drawn was that melon never competes with
                        # what we sell. The measurement was right and the
                        # reading was backwards. Melon is LOW-LABOUR -- plant
                        # once, water inside a window, harvest once -- where
                        # strawberry is high-labour. At PRIO_WEIGHT=14 the farm
                        # was labour-starved, so converting melon to strawberry
                        # starved the whole board and melon looked load-bearing.
                        # It was never load-bearing, only cheap, and cheapness
                        # only pays while labour is scarce. With PRIO_WEIGHT=1
                        # it is what the price curve always said it was: the
                        # one crop that craters to $1 by day 20.
                        # MELON_EARLY stays 12 (5 -> 41/120, 8 -> 22): the
                        # opening wave really does fund the bootstrap. It is
                        # only the second wave that was waste.
MELON_WAVE2 = 10        # REVERTED to the v17 value. This scored 178/240 against its
                        # immediate predecessor and confirmed out of sample, and
                        # it still LOSES ground against the frozen v17 reference:
                        # with all four of this round's late adoptions in, the
                        # agent scored 58/120 against v17 where it had scored
                        # 101/120 eight adoptions earlier. Reverting all four
                        # restores exactly 101-19-0. See LINEAGE at the head of
                        # the settled-constants block.
MELON_STOP = 12         # after this a melon tile is a wheat tile. Pulled in from
                        # 14: melon planted on day 13-14 first yields on day
                        # 23-24 and then occupies the tile through the window
                        # where wheat could have cycled twice. 79/120 in-sample
                        # and 77/120 out-of-sample, mean +7k. 16 and 18 also beat
                        # the control in-sample but fade out of sample (75 -> 62),
                        # so the gain is in stopping earlier, not in the exact day.

MAX_HANDS = 12          # hire cost is fib(n) *per day*, so a roster of n costs
                        # fib(n+2)-1 every single day: 10 hands is $143, 12 is
                        # $376, 14 is $986, 18 is $6,764 and 22 is $46,367. The
                        # last two bankrupt the farm outright -- both score
                        # **0/120** with a mean under $4,300.
                        #
                        # 12 is the peak and it is sharp: 116/120 in-sample and
                        # 117/120 out-of-sample, against 11 at 101/98, 13 at
                        # 111/102 and 14 at 52. The cliff is arithmetic -- the
                        # 13th and 14th hands cost 233 + 377 a day between them,
                        # more than the whole first twelve. Note a coarse grid
                        # hides this: sweeping 10/14/18/22 straddles the peak and
                        # makes the constant look flat-to-bad.
HANDS_EARLY = 4         # back to 4. The 6 was adopted in v17 under HERD_CAP=10
                        # and FEED_DAYS=4, where the farm had spare cash in the
                        # opening and the extra hands were close to free. With
                        # HERD_CAP=13 and FEED_DAYS=3 the opening is
                        # capital-hungry -- hands and cows bid for the same day-0
                        # money -- and the ranking inverts:
                        #   in-sample      4 -> 74   8 -> 42   (control 60)
                        #   out-of-sample  4 -> 77   5 -> 73   3 -> 52  (ctrl 60)
                        # 151/240 combined, 4 and 5 a plateau with 3 falling off.
                        # This also retires the story that used to sit here: the
                        # ~17% idle unit-turns were read as slack deliberately
                        # held for the peak, "the price of contesting the market".
                        # That explanation was fitted to a measurement taken in
                        # the old configuration. Hire fewer hands and the idle
                        # goes away *and* the win rate rises -- it was waste.
                        # 6 hands from day 0, not 4. Hands 5 and 6 cost
                        # fib(5)+fib(6) = $13/day between them, which the
                        # opening could always afford; what changed is that
                        # they now convert into work. On a farm spending 61% of
                        # its actions walking they bought almost nothing (6
                        # scored 45 and 42 of 120 at PRIO_WEIGHT=14); under
                        # nearest-first scheduling they buy real actions.
                        # 88/120 in-sample (88W-32L) and 79/120 out-of-sample
                        # (79W-41L, seats 38/41) against a 60/120 control.
                        # Joint with HANDS_DAY1 per 11.6 and the interaction is
                        # sharp: 6 with HANDS_DAY1=5 collapses to 26/120, 8 with
                        # DAY1=5 to 3/120. HANDS_DAY1 stays 7.
                        #
                        # A HIRE_BURST knob was added and REMOVED here. The hire
                        # block emits up to 6 HIREs a turn, and at cap=6 the
                        # opening block is 6 HIRE + 2 BUY_ANIMAL + 2 BUY_SEED =
                        # exactly maxMarketOrdersPerTurn, so `free` goes to 0
                        # and sells get no slot. Capping the burst fixes that
                        # and costs far more than it saves: burst 4 takes this
                        # to 55/120 and burst 3 to 48, and at HANDS_EARLY=4
                        # burst 4/3 score 20/18. The burst matters on days 7+
                        # where cap is 12 -- hiring is cash-limited hour by
                        # hour, so 6 attempts a turn over hours 0-3 fills a
                        # 12-roster where 4 attempts does not.
                        # Measured instead of argued: at HANDS_EARLY=6 the
                        # stock left unoffered on a full queue is 46 units /
                        # $1,992 a season against 4's 70 units / $1,506 -- no
                        # worse -- and every such turn falls on days 17-28,
                        # i.e. mid-season feed and seed buys, never the hire
                        # window. See test_agent.py section 9.
                        # Original note: the ramp is bought out of income,
HANDS_MID = 11          # one below MAX_HANDS, not the full roster. Follows
                        # HANDS_EARLY going 6 -> 4 earlier this round: the
                        # mid-game number was set when the early number was 6,
                        # and moving one moved the other.
                        #   in-sample      8 -> 35   10 -> 88   11 -> 91  (ctrl 60)
                        #   out-of-sample  9 -> 68   10 -> 76   11 -> 87  (ctrl 60)
                        # 178/240 combined. 11 beats 10 on both halves, which is
                        # why the missing in-sample cell was worth buying -- 10
                        # was the safe adoption and the worse one.
                        # The 12th hand costs fib(12) = $144/day, about $3,300 a
                        # season, for the least marginal work on the roster.
                        # was: the FULL roster from day 7, not from day 10 -- at
                        # MAX_HANDS=12 this value makes HANDS_DAY2 inert, so the
                        # ramp is now 4 hands while broke and 12 from day 7.
                        # Swept jointly with HANDS_EARLY per 11.6, which is the
                        # only way it is visible: worth +9 at HANDS_EARLY=4 and
                        # **-28** at HANDS_EARLY=8 (13/120), so the sign flips
                        # inside the grid and either constant alone reads as
                        # noise. 68/120 in-sample against a 59 null, and
                        # 78/120 out-of-sample against that control's 58 --
                        # it strengthens on held-out seeds, seats 37/41.
                        # HANDS_DAY1 re-swept underneath it and stays at 7:
                        # 6 -> 39/120, 5 -> 58, 4 -> 2.
                        # NOT a labour-throughput win, and the mechanism is
                        # still unknown: instrumented, the two extra hands buy
                        # +21 productive actions and +161 PASS. Recorded as
                        # measured-but-unexplained rather than dressed up.
HANDS_DAY1 = 7          #
HANDS_DAY2 = 10         # HANDS_MID was 8, fitted when the board was strawberry-
                        # led. With wheat on a third of the tiles the mid-game
                        # has far more work to service and the extra two hands
                        # cost only fib(9)+fib(10) = $89 a day: 110/120 in-sample,
                        # 106/120 out-of-sample, and it lifts the worst season to
                        # 36,605. 9 -> 85, 11 -> 89/97, so 10 is the peak.
                        # REVERTED: a HANDS_LATE_DAY=29 / HANDS_LATE=10 taper was
                        # adopted for one round at 73/120 in-sample, 68/120
                        # out-of-sample, and does not hold up. Two independent
                        # reasons. The intervention skips the 11th and 12th hire
                        # on the final day only, which is fib(11)+fib(12) = $233
                        # spent once; against the observed margin spread that can
                        # decide at most a handful of games, not the +13 claimed.
                        # And its out-of-sample number is not a confirmation at
                        # all -- the held-out seeds are what chose day 29 over day
                        # 28, so the arm was fitted on both sets. The neighbours
                        # (cap 11 at 68, day 28 at 73) are flat within noise; the
                        # collapse it cited sits several arms away, which is not
                        # the adjacent-arm collapse the method asks for.

CASH_RESERVE = 0        # the frontier opens $3,000 -> $9 and runs on $9 for two
                        # days. There is no rainy day inside 30 turns; every
                        # dollar not compounding by day 2 is a dollar wasted.
PRIO_WEIGHT = 1         # steps of walking traded per priority level. Was 14,
                        # which on an 18-step board let a unit cross the whole
                        # farm for one tier -- priority dominated distance
                        # almost completely. Two costs, and they compound: the
                        # walking itself, and tier-6 PLANT_WHEAT never running
                        # while any tier-0..5 chore existed anywhere on the map.
                        # Measured: from day 13 the farm is 0% idle with 15-37
                        # tiles bare, seeds in hand and the PLANT tasks queued.
                        # The frontier carries 0 empty tiles from day 11 to 27
                        # and closes on ~145k against our ~90k.
                        # 1 -> 118/120 in-sample and 118/120 out-of-sample
                        # (round 5), against a 56/57 control; 2 -> 108/117,
                        # 3 -> 110/101, 4 -> 81, 6 -> 64, 10 -> 53, 14 -> 56.
                        # It also carries the best worst case in the table
                        # ($46,875 vs the control's $33,641) -- nearest-first
                        # does not starve FEED, it protects it, because a unit
                        # no longer abandons a nearby animal to cross the board.
                        # FINDINGS 10.9 filed this constant as "flat/inert on
                        # this farm shape"; that was measured before anyone knew
                        # the late game was labour-starved.
BUILD_PRIO = 6          # tier for BUILD_PASTURE -- the farm's only growth lever
PROJ_FRACTION = 0.5     # how far into the rest of the season to price an animal
PLANT_PRIO = 7          # tier for PLANT_*, endgame included -- see `_tasks`
WHEAT_RUSH_DAY = 26     # day from which wheat replanting jumps to
WHEAT_RUSH_PRIO = 2     # WHEAT_RUSH_PRIO. 99 means never = the exact control.
                        # Aimed at the one gap the frontier diff still shows:
                        # on days 24-28 we carry 13-24 bare tiles where the
                        # frontier carries 1, and its day-26 board is 57 wheat
                        # to our 18. WHEAT_PLANT_PRIO=9 parks replanting at the
                        # bottom tier, which is right mid-season and plausibly
                        # wrong in the last five days, when a wheat tile has
                        # exactly one cycle left to pay for itself and nothing
                        # else will ever use the ground.
                        # FINDINGS 8.4 tried a rush before: "adopted at +33,
                        # reverted at -15 once fertilizer targeting changed
                        # underneath it; a saturated comparison against a stale
                        # baseline" -- i.e. never cleanly measured either way.
                        # Now it is: 98/120 in-sample (98W-22L) and 92/120
                        # out-of-sample (92W-28L, seats 46/46) against a
                        # 60/120 control on both sets. Clean peak, and no null
                        # constant makes this shape: 20 -> 22, 23 -> 71,
                        # 25 -> 90, 26 -> 98, 27 -> 82, 99 -> 60.
                        # Wheat first-yields in 2 days and planting stops at
                        # DAYS-3, so a rush at 26 buys the last cycle the
                        # season can actually pay out, on ground nothing else
                        # will ever use again.
WHEAT_PLANT_PRIO = 9    # the BOTTOM tier, below melon/dig (7) and strawberry
                        # (5). Raised from 6 after PRIO_WEIGHT went to 1, and
                        # the direction is the opposite of what fixing the
                        # planting starvation suggests -- it follows from it.
                        # At PRIO_WEIGHT=1 wheat already replants 9-25 tiles a
                        # day, so the question stopped being "does planting
                        # happen" and became "what does a unit abandon to do
                        # it". Wheat is the cheapest crop on the board ($10 a
                        # seed) so it is what should wait: pushed to the bottom,
                        # units clear the chore in front of them and plant a
                        # bare tile when one is *near*, which is exactly what
                        # nearest-first scheduling is good at.
                        # Sharp peak, and a null constant cannot make this
                        # shape: 3 -> 32/120, 6 -> 60 (control), 9 -> 69,
                        # 12 -> 21, 15 -> 9. Out of sample 9 scores 76/120
                        # (76W-44L, seats 37/39) against the control's 60, so
                        # it strengthens on held-out seeds, and lifts the worst
                        # season from $30,162 to $45,733.
                        # Original note, still true at tier 6: wheat replanting
                        # ordinary harvest/build action for most of the season
STRAW_PLANT_PRIO = 5    # strawberry planting, one tier above wheat replanting.
                        # At the bottom tier the ramp never finishes: day 7 of
                        # seed 7 held 10 seeds beside 18 bare reserved tiles and
                        # planted 2, and no unit was ever idle while a seed was
                        # held -- the tiles lose a race for unit-turns, not for
                        # cash or ground. 92/120 in-sample, 87/120 out-of-sample
                        # (null 60). The win is *earlier*, not more: the block
                        # fills by day 11 with no stranded seed, where tier 7
                        # left 6 tiles bare on day 12 and 3 seeds unplanted for
                        # the rest of the season. Sharp peak -- tier 4 collapses
                        # to 19/120 by outranking CARE, and tier 6 to 42/120 by
                        # tying with the wheat replant it would displace.
TOMATO_TILES = 0        # tomato is the one crop nobody in the field sells, so its
                        # price is never pushed above target and it spends the
                        # whole season climbing the *below* curve: $60 on day 0,
                        # $380 on day 22, $857 on day 27 (measured, rank-1 replay
                        # 104859742). Strawberry and wool are at $1 by then --
                        # every agent including this one dumps them.
                        # The sell side is nearly free: below target the curve is
                        # linear at 0.4*60/200 = $0.12 a unit, so a thousand units
                        # move the price $120. Strawberry above target is linear
                        # at $1.92 a unit and crashes after ~60.
                        # Sizing this block off the projected price instead of a
                        # flat count is measured and dead: gating on `proj`
                        # scored 54/120 at a $100 floor, 50 at $150 and 44 at
                        # $250 against a 60 control, monotone in how hard it
                        # gates. Even a $85 tomato tile beats the wheat it
                        # displaces -- four ticks at $85 against six units at
                        # $43 -- so the shop lottery is not worth reacting to.
                        #
                        # CARROT and EGG are the other two hinge products and
                        # neither is worth planting, for one reason: a hinge only
                        # runs if the town's drain clears the knee *after* our own
                        # supply is subtracted, because selling refills the very
                        # shortage we came for. On the expected draw -- 8 shop
                        # instances over 8 types, so one of each -- tomato drains
                        # 338 a season against our 64, leaving 274 against a knee
                        # of 200, a 37% margin. Carrot drains 494 against our 80,
                        # leaving 414 against a knee of 450: it never reaches it,
                        # and measured it scores 46/120 at 8 tiles and 37 at 16.
                        # Eight geese would supply 416 eggs against a 338 drain
                        # and cancel it outright (see BUYABLE).
                        #
                        # How much this block is worth depends entirely on
                        # FEED_DAYS, and neither constant is worth much alone.
                        # All four cells against one fixed opponent,
                        # `opp_notomato.py` (FEED_DAYS=3, TOMATO_TILES=0):
                        #
                        #                  TILES=0   TILES=16   tomato worth
                        #   FEED_DAYS=3      60*       114          +54
                        #   FEED_DAYS=4      93         90           -3
                        #   (*) mirror of the opponent, so 60 by construction
                        #
                        # Swept alone at FEED_DAYS=4, tomato reads as noise and
                        # would have been rejected. Swept alone with tomato at 0,
                        # FEED_DAYS=3 *loses* to 4 by 93-27. They only pay
                        # together, and the first measurement of each was taken
                        # while the other sat at its wrong value -- which is why
                        # tomato first measured 76 and later 114.
                        #
                        # Do NOT hold the crop for the end. The rank-2 agent
                        # (2964.9) sells its first tomato and first egg on day 29
                        # and it does not transfer: 46/120 holding to day 27,
                        # 9 to day 28, 6 to day 29 against a 60 control, and
                        # 94/120 against 114 with the opponent growing no tomato
                        # at all -- so it loses uncontested too, not just because
                        # a mirror opponent takes the curve first. Tomato peaks
                        # on day 27 ($857) and falls to $707 as it is sold, so
                        # harvesting into days 24-27 already captures the rise;
                        # holding sells into our own dump and parks 64 units in
                        # a 100-unit shed that discards its overflow nightly.
TOMATO_DAY = 17         # tomato is ongoing with first=8, interval=1, max_yield=4,
                        # so a plant produces on exactly four days, seven days
                        # after planting. Planted day 17 those four ticks land on
                        # days 24-27 at $582/$704/$838/$857. Day 14 lands them on
                        # 21-24 at a mean $430; day 20 loses a tick off the end.
                        # The rank-1 agent plants on day 16.
TOMATO_STOP = 21        # after this the block lapses back to wheat. Standing
                        # plants keep producing -- nothing uproots a healthy crop.
TOMATO_PLANT_PRIO = 4   # one tier above strawberry planting. A tomato tile is
                        # worth ~$3,100 unfertilized over its four ticks; nothing
                        # else on the board is close, and the window is narrow.
WATER_PRIO = 3          # a plant that weeds over tonight, or produces tonight
FERT_PRIO = 3           # REVERTED to the v17 value. This scored 171/240 against its
                        # immediate predecessor and confirmed out of sample, and
                        # it still LOSES ground against the frozen v17 reference:
                        # with all four of this round's late adoptions in, the
                        # agent scored 58/120 against v17 where it had scored
                        # 101/120 eight adoptions earlier. Reverting all four
                        # restores exactly 101-19-0. See LINEAGE at the head of
                        # the settled-constants block.
PLANT_HOUR = 22         # `_new_plant` sets consecutive_unwatered = 1, so a crop
                        # must be watered the *same day* it goes in or it weeds
                        # over -- hence a cutoff at all. But the cutoff is now
                        # nearly worthless: wheat covers a third of the board and
                        # replants continuously, so hours 21-22 are prime
                        # replanting time and forbidding them costs far more than
                        # the occasional seed lost. 22 wins 111/120 in-sample and
                        # 117/120 out-of-sample; 20 is the old value, 23 (no
                        # cutoff at all) still beats it at 96/93, and tightening
                        # is a catastrophe -- 17 and 14 both score **0/120**.
FEED_DAYS = 3           # was 4. Found in the head-to-head replay 105073754, not by
                        # sweeping: on day 0 the rank-177 agent and this one spend
                        # the same ~$2,950, and it buys 2 cows where we buy 1 and
                        # 16 units of feed wheat we do not need yet. By day 3 it
                        # holds 6 animals to our 4, and that compounds through
                        # fertilizer and milk all season. This gate reserves feed
                        # money *before* animals can be bought, so it was the
                        # thing deciding it. 61/120 in-sample and 71/120 out of
                        # sample against a control that landed on exactly 60
                        # both times -- and it wins at equal mean income
                        # (89,518 against 89,669), which is relative gain rather
                        # than the richer-farm-fewer-wins trap that killed the
                        # herd, fertilizer, hands and seed-order arms.
                        # only grow the flock while we can feed it this long, and
                        # reserve that much feed money before anything else is
                        # spent. Raised from 3 once wheat took a third of the
                        # board: 94/120 in-sample and 91/120 out-of-sample. It is
                        # a second brake on herd growth and pulls the same way as
                        # HERD_CAP, which is why both moved this round. Narrow
                        # ridge -- 5 still wins (87/85) but 6 collapses to 41/44,
                        # because past that the reserve starves the seed budget.
FERT_ONGOING_ONLY = 1   # 1 = fertilize strawberry only. A fertilized tick is
                        # worth ~$250 on strawberry and ~$50 on wheat, against a
                        # fertilizer that sells for ~$45-65 -- so on wheat the
                        # trade is roughly break-even before the walking.
FERT_CARRY = 3          # was 2, and like HERD_CAP the old value was a symptom of
                        # a smaller herd. Swept at HERD_CAP=10 it decayed hard --
                        # 4 scored 37/120, 8 scored 33 -- because ten animals do
                        # not make enough fertilizer for a unit to carry more of
                        # it usefully. At HERD_CAP=13 the whole curve lifts and
                        # flattens: 3, 4 and 6 all land 77-83 out of sample.
                        #   in-sample      3 -> 67   4 -> 68   (control 60)
                        #   out-of-sample  3 -> 83   4 -> 79   6 -> 77  (ctrl 60)
                        # 3 and 4 are a coin toss on 240 games (150 vs 147); 3
                        # takes it on the out-of-sample half, which is the half
                        # this file's own convention trusts.
                        # FERT_ONGOING_ONLY stays 1. Fertilizing non-strawberry
                        # crops scores 0/120 at both carry values and at both
                        # herd sizes -- it is a priority-tier defect (a prio-3
                        # fertilize task starves watering), not a shortage that
                        # more fertilizer fixes. Measured dead three times now.
                        # fertilizer a unit takes from the shed to spend on
                        # production ticks, and the amount it keeps rather than
                        # banking. 0 disables fertilizing altogether, since the
                        # only other source is whatever a unit is holding when it
                        # walks past a crop. Swept 1-8; 2 won, decaying to
                        # 33/120 by 8.
WHEAT_CARRY = 6         # one hand holding all the wheat is every hand behind it
                        # unable to FEED. Swept 3-50; 6 won 47/48.


# ---------------------------------------------------------------------------
# LINEAGE. FINDINGS 13.11 says to re-run a frozen reference EVERY round. This
# round ran it twice in twelve adoptions and the gap is the whole story:
#
#   after  8 adoptions   101-19-0 vs v17.py
#   after 12 adoptions    58-62-0 vs v17.py     <- below the 60 null
#   reverting those 4    101-19-0 vs v17.py     <- reproduces exactly
#
# All four late adoptions -- FERT_PRIO=2, MELON_EARLY=6, MELON_WAVE2=14,
# STRAW_TILES=24 -- beat their immediate predecessor by 134-178 of 240 AND
# confirmed on disjoint seeds, and every one of them costs ground against a
# fixed opponent. Measured individually against v17: melon pair -28 together,
# STRAW_TILES -15, FERT_PRIO -3.
#
# Out-of-sample confirmation cannot catch this. Fresh seeds test whether a
# result generalises across BOARDS. Nothing in that protocol tests whether it
# generalises across OPPONENTS, and both halves were measured against the same
# immediate predecessor while baseline.py advanced after each adoption.
#
# Rule: an adoption is not adopted until it is measured against a frozen
# reference several generations back. A win against the moving baseline is a
# candidate, not a result.
# ---------------------------------------------------------------------------
# Swept and settled at their current values under HERD_CAP=13 / SHEEP_CAP=6 /
# FEED_DAYS=3 / HANDS_EARLY=4 / HANDS_MID=11 (this round). Re-sweeping these
# without first changing something they depend on is wasted compute:
#
#   HERD_CAP      15 -> 35, 17 -> 11        MAX_HANDS   10 -> 25, 14 -> 0
#   FEED_DAYS     2 -> 64, 4 -> 21          HANDS_DAY1/2  no cell beats 7/10
#   PRIO_WEIGHT   3 -> 0,  6 -> 0           WATER_PRIO  2 -> 12, 4 -> 63
#   TOMATO_DAY    15 -> 63, 19 -> 56        WHEAT_FRACTION see its own note
#   WHEAT_CARRY   9 -> 8,  12 -> 4          BUILD_PRIO  3/6/9 all 60
#
# Every priority tier is now measured under this configuration. FERT_PRIO
# moved (3 -> 2, see its own note); the rest all hold, several sharply:
#
#   WATER_PRIO         2 -> 20   4 -> 50    (re-checked after FERT_PRIO moved
#                                            above it; the cascade stopped here)
#   STRAW_PLANT_PRIO   3 -> 16   7 ->  8
#   TOMATO_PLANT_PRIO  2 -> 28   6 -> 51
#   WHEAT_PLANT_PRIO   7 -> 40  11 -> 31
#   PRIO_WEIGHT        3 ->  0   6 ->  0
#   PLANT_PRIO         5 -> 29   9 -> 43
#   WHEAT_RUSH_PRIO    1 -> 50   4 -> 55
#
# STRAW_PLANT_PRIO and FERT_PRIO were both absent from an earlier version of
# this list that claimed to be complete. One was already right and the other
# was worth 171/240. Audit the list against the file, not against memory --
# and note that the commit which first wrote that sentence ALSO claimed every
# tier was covered while PLANT_PRIO and WHEAT_RUSH_PRIO were not. Both turned
# out correct, but the claim was made from memory in the act of warning
# against exactly that. `grep '^[A-Z_]* *=' main.py` is the check.
#
# Still unswept under this configuration, in rough order of prior:
#   MELON_EARLY / MELON_LATE / MELON_WAVE2 / MELON_STOP  (tuned when the board
#     carried 24 melon tiles and a 10-animal herd)
#   STRAW_STOP / STRAW_TILES / TOMATO_STOP  (the acreage handoff tomato sits in)
#   WHEAT_RUSH_DAY  (adopted two sessions before any of this round's changes)
#   LAND_DAY4 / CASH_RESERVE / PLANT_HOUR
#
# WHEAT_CARRY is worth a note because the hypothesis behind it was reasonable
# and wrong. We make 335 PICKUPs a game against the frontier's 133-254, and
# every one is a trip to the shed; with 13 animals to feed instead of 10 it
# looked like the carry was too small to amortise the walk. It is not: 9 and
# 12 score 8 and 4 of 120. Inventory room costs more than trips do -- a unit
# holding 12 wheat has no room for produce -- which is the same shape as the
# FERT_CARRY decay this file already records.
#
# Dead levers -- the swept values produce byte-identical games, so the constant
# is not reachable in the current configuration at all:
#
#   ANIMAL_TILES    (herd term in `n_animal` always caps lower)
#   PROJ_FRACTION   (0.5 and 0.7 identical)
#   BUILD_PRIO      (6 and 9 identical)
#
# OPEN LEAD, not yet tested. We sell 190-225 FERTILIZER a game -- at $7-60
# once the price has decayed -- while performing only 51 FERTILIZE acts
# against 300+ opportunities (strawberry produces every 2 days from day 10;
# tomato four times from day 24). A fertilized tick doubles a tomato unit
# worth $582-857. BUY_PRODUCT is legal for FERTILIZER and we never use it.
# The reason this is a lead and not a change: buying puts fertilizer in the
# SHED, units need it in HAND, and the shed pickup was deleted because the
# wheat pickup claims the shed-standing unit first. So it needs two coupled
# changes, and at the measured 0.60 live rating per point of local margin
# even a strong result is worth about +20 against a 1,916-point gap.
#
# Measured dead outright, three times across two configurations:
#   FERT_ONGOING_ONLY=0 -> 0/120   (prio-3 fertilize task starves watering)
#   carrot, geese, holding tomato for the endgame -- see TOMATO_TILES.
# ---------------------------------------------------------------------------
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
    # Tomato takes its block from what strawberry gives back: `STRAW_STOP` is 12
    # and `TOMATO_DAY` is 17, so by the time this reservation opens the tiles it
    # wants are already falling through to wheat.
    tom = (rest[len(straw):][:TOMATO_TILES]
           if TOMATO_DAY <= day <= TOMATO_STOP else [])
    # Anything strawberry and tomato do not claim -- and everything they give
    # back once the reservations lapse -- is wheat.
    return {"ANIMAL": animal, "WHEAT": wheat + rest[len(straw) + len(tom):],
            "STRAWBERRY": straw, "MELON": melon, "TOMATO": tom}


def _shape(f, x, T=None):
    """The environment's price shape functions; log is ln(1+x) so f(0) = 0.

    `hinge` is the one 1.32.6 did not have, and the whole reason the old mirror
    of this table priced tomato at a sixth of its real value. It is linear in
    x/T below the knee and quadratic above it, so f(T) == 1 like every other
    shape and `target` keeps meaning the same thing.
    """
    x = max(0.0, x)
    if f == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return (x * x if f == "sq" else math.sqrt(x) if f == "sqrt"
            else math.log1p(x) if f == "log" else x)


def _price_at(item, inv):
    """The environment's price curve evaluated at a hypothetical inventory."""
    p = MARKET_PARAMS[item]
    f, target = p["below"] if inv < I0 else p["above"]
    amp = target * p["base"] / _shape(f, p["T"], p["T"])
    return max(1.0, p["base"] + (1 if inv < I0 else -1)
               * amp * _shape(f, abs(inv - I0), p["T"]))


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
            spec = ANIMALS[t["animal"]]
            # Feeding is survival: two missed days and the animal is gone
            # forever. Except at the end -- the final refresh that still
            # produces something sellable is day 28's, and base production
            # lands whether or not the animal was fed. Day 28's feed is only
            # worth its wheat if it unlocks a banked bonus at that refresh, or
            # resets an escape counter that would wipe stock off the tile.
            feed_worth = (day < DAYS - 2 or t["consecutive_unfed"] >= 1
                          or (t.get("pending_care_bonus", 0) > 0
                              and _next_tick(t["placed_day"], spec, day) == day))
            if not t["fed_today"] and have_wheat and day < DAYS - 1 and feed_worth:
                out.append((0 if t["consecutive_unfed"] >= 1 else 2, x, y, "FEED"))
            if t["yield_units"] >= 3:
                out.append((1, x, y, "HARVEST"))       # don't stall at max_held
            # One CARE on a cow is worth a whole $336 milk -- the single
            # highest-value action on the board. The bank pays out on the first
            # production refresh *after* the day it is banked, so it only lands
            # if that tick comes by day 28. The old `day < DAYS - 2` gate was
            # species-blind: an interval-3 sheep can run out of payable ticks
            # as early as day 25 while a well-phased cow still has day 27.
            if (not t["cared_today"] and t["fed_today"]
                    and _next_tick(t["placed_day"], spec, day + 1) <= DAYS - 2):
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
                out.append((STRAW_PLANT_PRIO, x, y, "PLANT_STRAWBERRY"))
            elif role == "TOMATO":
                out.append((TOMATO_PLANT_PRIO, x, y, "PLANT_TOMATO"))
            # ANIMAL is here as well as above, and that is the whole fix: with
            # `build_budget == 0` an empty ANIMAL tile used to match no branch at
            # all and emit no task, so it stayed bare for the rest of the season.
            # It is not a rare state -- once the herd reaches HERD_CAP the budget
            # is 0 permanently, and `_roles` re-sorts by distance at each land
            # unlock, so standing animals rank out of the innermost slice while
            # empty tiles rank into it. Measured at 21-41 tile-days a season from
            # day 10, on the lowest-walk tiles on the board; a weed was observed
            # squatting one for five days, and weeds only spawn on empty tiles.
            # Wheat, not strawberry: it matches the existing fall-through and
            # keeps this separate from any acreage change.
            elif role in ("WHEAT", "ANIMAL") and day <= DAYS - 3:  # wheat first-yields day 2
                # Endgame rush, if enabled -- see WHEAT_RUSH_DAY.
                if day >= WHEAT_RUSH_DAY:
                    out.append((WHEAT_RUSH_PRIO, x, y, "PLANT_WHEAT"))
                    continue
                # Promoted to tier 6 for the whole season: 110/120 in-sample,
                # 118/120 out-of-sample vs the tier-7 baseline (parity 57).
                # This is not the day-25 rush that 8.4 reverted -- that promoted
                # planting only in the endgame, inside the old fertilizer
                # config. At tier 7 a wheat tile competes with DIG and ripe
                # harvests and stays bare for most of the season; one tier up it
                # replants behind the builds without outranking any harvest.
                out.append((WHEAT_PLANT_PRIO, x, y, "PLANT_WHEAT"))
    return out


def _next_tick(placed, spec, start):
    """First end-of-day >= start whose refresh produces for this animal.

    Mirrors `_daily_refresh_animals`: end of day d produces iff
    d+1 - placed - first_yield_day is >= 0 and divisible by the interval.
    """
    k = placed + spec["first"] - 1
    return k if start <= k else start + (-(start + 1 - placed - spec["first"])
                                         % spec["interval"])


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
    # nowhere to stand, and the opening buys three of them in the first order
    # block -- four by the end of day 0 -- before a single pasture exists. While
    # any are waiting, housing them outranks everything.
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
    #    A single hiring hour is a trap whenever `cap` is small: `(4-1)//6 == 0`,
    #    so the entire opening roster is attempted at hour 0 -- which
    #    CASH_RESERVE=0 guarantees is the day's cash minimum. Measured on seeds 7
    #    and 13: day 4 opens at $0.00, all four hires are refused, $1,139 lands at
    #    hour 1, and the farm works the remaining 23 turns with no hands at all.
    #    `hires_today` counts only *successful* hires -- the environment's
    #    `_do_hire` returns before incrementing when it cannot pay -- so retrying
    #    while the roster is short is self-limiting: a day that fills at hour 0
    #    emits nothing afterwards and is byte-identical to before.
    if me["hires_today"] < cap and hour <= max(3, (cap - 1) // 6):
        for _ in range(min(6, max(0, cap - me["hires_today"]))):
            orders.append(["HIRE"])

    # 3. Land, on the calendar. See LAND_DAYS.
    n_extra = len(me["unlocked_quadrants"]) - 1
    calendar = LAND_DAYS + [LAND_DAY4]   # read LAND_DAY4 here so it stays sweepable
    if (n_extra < len(calendar) and day >= calendar[n_extra]
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
    for crop in ("WHEAT", "MELON", "TOMATO", "STRAWBERRY"):
        short = wanted["PLANT_" + crop] - priv["seeds"].get(crop, 0)
        buy = max(0, min(short, int(spendable // CROPS[crop]["seed"])))
        if buy:
            orders.append(["BUY_SEED", crop, buy])
            spendable -= buy * CROPS[crop]["seed"]

    # 6. Sell everything that is not being held back as feed.
    #
    #    This block used to ration its sells four separate ways -- price floors
    #    on milk and wool, a shed-pressure release for those floors, a per-turn
    #    drip-feed chunk, and a trigger that cleared stock ahead of the
    #    opponent's visible dump. Every one of them was swept and every one of
    #    them lost, converging on the same ~87/120: floors off 87, always-dumping
    #    87, both 87.
    #
    #    They lose because they solve a solo problem. Orders clear one unit at a
    #    time, alternating between the two players, so stock we hold back is
    #    simply the high part of the curve left standing for the opponent -- and
    #    the leaderboard pays for beating them, not for a tidy price. Holding
    #    also loses outright at the end, where reward is money alone and stock in
    #    the shed on the last tick is worth exactly $0. FINDINGS 10.16.
    #
    #    Wheat is the one real exception and it is not a market judgement: wheat
    #    in the shed is feed. Selling it and buying it back next turn was once
    #    the single largest market flow of the season.
    keep = {"WHEAT": 0 if day >= DAYS - 1 else n_animals + 10}
    sells = []
    for p in PRODUCTS:
        have = max(0, shed.get(p, 0) - keep.get(p, 0))
        if have > 0:
            sells.append((have * prices.get(p, 0), p, have))
    # Ten orders clear a turn and hiring can take six of them, so the slots that
    # are left have to go to the most valuable stock, not to whatever PRODUCTS
    # happens to list first.
    #
    # Held back from `orders` and merged at the return, because the *index* an
    # order sits at is priced. `_process_market` walks queue positions -- only
    # orders at the same index interleave, and index 0 fully resolves, walking
    # the price, before index 1 is quoted. Being first weakly dominates for a
    # sell: matched at the same index both players are quoted the identical
    # pre-commit inventory and split the curve unit for unit; ahead of them we
    # take the whole undegraded curve. Measured penalty for slot 8 against slot
    # 0 is 88% on milk, 42% on melon, 35% on glut wool -- and milk, melon and
    # wool are exactly what sits at slots 7-9 today, behind six HIREs. A mirror
    # cannot see any of this: both sides sit at identical slots, which is why it
    # survived six rounds of benchmarking.
    sells = [["SELL", p, q] for _, p, q in sorted(sells, reverse=True)]

    # ---------------- unit actions -----------------------------------------
    seeds = dict(priv["seeds"])
    stock = {a: shed.get(a, 0) for a in ANIMALS}
    # Local tallies, never `shed` itself: `obs` is the live observation and two
    # units in the same turn must not both be handed the last unit of stock.
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
            elif (unfed > sum(i.get("WHEAT", 0) for i in invs)
                  and inv.get("WHEAT", 0) == 0 and shed.get("WHEAT", 0) > 0):
                # `unfed` alone asks "is any animal hungry", not "will *this*
                # unit feed one". With 13 animals and 12 units every unit fetched
                # WHEAT_CARRY each morning, ~13 feeds happened, and the rest rode
                # back to the shed at midnight: measured 324 pickups a game
                # hauling 1,365 wheat to deliver 292 feeds. Counting the wheat
                # already in hand across the roster stops the herd being
                # provisioned a dozen times over.
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
            # A shed PICKUP of fertilizer used to sit here, meant to close the
            # loop between COLLECT_FERTILIZER (at a pasture) and FERTILIZE (on a
            # crop). Deleted: it fired 0-2 times a season against 158-248 turns
            # that wanted fertilizer, for two reasons that both hold every turn.
            # The wheat PICKUP above claims the only unit standing on the shed at
            # hour 0 (hands have not respawned yet), and FERTILIZER is in
            # PRODUCTS with no `keep` entry, so the sell block empties the shed of
            # it every hour 0 anyway. The live source was never this: it is
            # COLLECT_FERTILIZER in the field, which leaves the collecting unit
            # holding FERT_CARRY units where the crops are -- so FERT_CARRY stays,
            # governing the banking threshold above, and the 34-38 real FERTILIZE
            # acts a season are unaffected.
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

    # Sells take the slots the one-shot orders leave free, so they lead the queue
    # without displacing anything: the set sent is identical to `(orders +
    # sells)[:10]`, only its order changes. The feed BUY_PRODUCT ends up behind
    # them, which is the right way round -- a buy wants the price walked down.
    free = max(0, 10 - len(orders))
    return {"farmer": acts[0], "hands": acts[1:],
            "market": (sells[:free] + orders + sells[free:])[:10]}
