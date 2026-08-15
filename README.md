# Kaggriculture agent

This repository has two parts. The first is a submission for the Kaggriculture
competition. The second is the harness that measures changes to it.
Kaggriculture is a two-player farming simulation. Each game runs 30 days of 24
turns each. The player with the most money at the end wins.

`main.py` is the whole submission. It is one `agent(obs)` function. It uses
only the standard library (`math`, `collections`). It keeps no state between
turns. Everything else in the repository answers one question: did that edit
help?

The game rules are in the second half of this file.

## Files

| Path | What it is |
| :--- | :--- |
| `main.py` | The agent. This is the file that gets submitted. |
| `baseline.py` | Frozen copy of `main.py`. It is the head-to-head opponent for every benchmark. It is byte-identical to `main.py` right now. |
| `bench.py` | 60 seeds × 2 seats = 120 games in parallel. It can also sweep constants. |
| `validate.py` | Checks the benchmark itself: determinism, true parity, seat balance, out-of-sample seeds. |
| `play.py` | One episode, day-by-day table, optional `replay.html`. |
| `test_agent.py` | Dependency-free smoke test on invariants (legal actions, order caps). |
| `FINDINGS.md` | The measurement log. Comments in `main.py` cite it by section number. |

## How the agent decides a turn

`agent(obs)` runs the same pipeline on every one of the 720 turns. It is
stateless. It re-derives everything from the observation on each call. It
keeps no per-unit target or plan to synchronize.

**1. Census.** Count the herd, the empty structures, the unfed animals, and
`pending` stock. `pending` means animals bought but not yet standing on a
tile. The count includes both the shed and the unit inventories.

**2. Capacity gate.** `capacity = min(HERD_CAP, herd + affordable)`.
`affordable` is `spendable // (wheat_price * FEED_DAYS)`. Cash limits the
flock, not tiles, because feed is bought, not grown, and a starved animal is
a total loss. `pending` stock is exempt from this gate. The gate throttles
buying only. It must never refuse to house stock that is already paid for.

**3. Price projection** (`_projected`). This step re-implements the
environment's price curve. It evaluates each animal product at a half-season
horizon, using the herds on *both* boards and the drain from unlocked shops.
A cow's milk does not reach the market for 8 days. So ranking on today's spot
price would fill every pasture with one species before any feedback arrives.
`_best_species` picks cow or sheep by `RATE × projected price`. This choice
self-balances: each cow bought lowers the projected milk price and shifts the
next buy toward wool.

**4. Tile roles** (`_roles`). Every unlocked tile gets one role. The roles
come from *ordered lists*:

- `ANIMAL` — the tiles closest to the shed by distance, including the four
  shed-adjacent tiles. A pasture built on one of these is fed at zero walking
  cost.
- Crops — sorted by `(quadrant, distance)`, **not** by distance alone. Sorting
  by pure distance gives each crop a ring, and each ring's consecutive tiles
  sit on opposite edges of the board. Blocking by quadrant instead gives
  contiguous slabs of tiles. This change cut the mean walk before a
  productive action from 3.70 tiles to 1.19.

`_roles` carves in a fixed order: animals, then melon, then wheat. Strawberry
takes what is left. So the three constants ahead of it set strawberry acreage,
and `STRAW_TILES` does not. See the strategy section below.

Reservations *expire*, and that expiry is the endgame plan. Melon's
reservation lapses on day 12, and strawberry's lapses on the same day. As
those plants are harvested or decay, their tiles fall through to wheat
automatically. This needs no special-case code.

`MELON_STOP` moved from day 14 to day 12 this round, and it won 79/120
in-sample and 77/120 out-of-sample. A melon planted on day 13 first yields on
day 23. It then holds the tile through a window in which wheat could have
cycled twice.

**5. Task list** (`_tasks`). This step emits `(priority, x, y, op)` for all
outstanding work. Priorities are **fixed tiers, not dollar values**. An
earlier version priced tasks by live market value instead and scored 17k
against this version's 37.5k. The reason: a $1,500 melon harvest reliably
outbids a $250 `FEED` task, and the flock starves. Deadlines drive this game.
Feeding is worthless tomorrow.

| Prio | Ops |
| :--- | :--- |
| 0 | `FEED` an animal that missed yesterday (dies tonight) |
| 1 | `HARVEST` at the yield cap, `PLACE` an animal on a matching structure |
| 2 | `FEED`, `BUILD_PASTURE` while animals wait in the shed |
| 3 | `WATER` a plant that weeds over tonight or produces tonight, `FERTILIZE` |
| 4 | `CARE` (one care on a cow is worth a whole $336 milk) |
| 5 | `COLLECT_FERTILIZER`, `WATER` for the yield bonus, `PLANT_STRAWBERRY` |
| 6 | `BUILD_PASTURE` normally, ordinary `HARVEST`, `PLANT_WHEAT` |
| 7 | `PLANT_MELON`, `DIG` a weed |

`FERTILIZE` moved from tier 5 to tier 3, and this is the weakest adopted
result of the round. It won 77/120 in-sample and 70/120 out-of-sample, which
pools to 147/240 against a null of 120. The two seed sets disagree on whether
tier 3 or tier 4 is the argmax, and both arms come out seat-imbalanced. Read
it as "somewhere in 3 to 4 beats 5", not as an exact optimum. Tier 6 is
clearly wrong at 20/120, and tier 2 adds nothing at 72/120.

**The bottom tier is where a task goes to die.** This is the largest single
lesson of rounds 4 and 5, and it has two independent measurements. Wheat
replanting sat at tier 7 and mostly never ran, so a wheat tile stayed bare for
most of the season. Promoting it to its own tier 6 won 110/120 in-sample and
118/120 out-of-sample. Strawberry planting sat at tier 7 as well. On day 7 of
seed 7 the agent held 10 seeds beside 18 bare reserved tiles and planted 2,
and no unit was ever idle. Promoting it to tier 5 won 92/120 in-sample and
87/120 out-of-sample.

Both promotions are sharp peaks, not plateaus. Strawberry at tier 4 falls to
19/120, because it then ties `CARE` and outranks it on the coordinate
tie-break. Strawberry at tier 6 falls to 42/120, because it then ties the
wheat replant and displaces it. A promoted task needs its own band. Sharing a
band with work that matters is worse than staying at the bottom.

Both endgame animal gates are species-aware. `_next_tick(placed, spec, start)`
mirrors the environment's `_daily_refresh_animals`. `CARE` runs only if the
payout tick arrives by day 28, which is the last refresh whose output is still
sellable. `FEED` on day 28 runs only if it unlocks a banked care bonus at that
day's tick, or resets an escape counter. Base production lands whether or not
the animal was fed. The old blanket `day < DAYS - 2` gate was species-blind: an
interval-3 sheep can run out of payable ticks on day 25 while a well-phased cow
still has day 27. The two gates won 75/120 on both seed sets.

**6. Market orders** follow a fixed spend order, truncated to the 10 orders
that clear per turn: buy feed wheat → `HIRE` (ramped, cost is `fib(n)` per
day) → `BUY_LAND` on the calendar → animals → seeds → sells. Each stage
subtracts from `spendable`. This reserves the feed budget before strawberry
seed, at $100 a tile, can consume it. The sell stage then releases everything
the shed holds.

**Selling is unconditional, and it is the least intuitive result in this
file.** The agent used to ration its sells four ways: price floors on milk and
wool, a shed-pressure release for those floors, a per-turn drip chunk, and a
trigger that cleared stock ahead of the opponent's visible dump. Each one was
swept and each one lost, all converging on the same 87/120. They lose because
they solve a solo problem. Orders clear one unit at a time, *alternating
between the two players*, so stock we hold back is the good part of the price
curve left standing for the opponent. Stripping the block won 87/120 in-sample
and 76/120 out-of-sample, and it deleted 40 lines.

The one product still held back is feed wheat, and that is not a market
judgement. Selling the feed and buying it back next turn was once the single
largest market flow of the season.

`HERD_CAP` follows the same logic. A 14-animal herd closes milk at $7 and a
12-animal herd closes it at $135. Both changes make our own farm *poorer* in a
mirror match, and both win head-to-head, because the leaderboard pays for
market share rather than for farm income. A mirror match, or any
solo-optimality argument, will reject exactly the changes that win. Measure
head-to-head.

**7. Unit assignment** runs in three passes:

- *Shed work* — a unit standing on a shed tile banks produce, restocks
  wheat, collects an animal that has an open structure, or carries
  fertilizer out to the field. The unit never drops wheat, animals, or
  fertilizer while carrying them for work: `DROP`/`PICKUP` of working stock
  forms an infinite loop, and this bug once wasted 962 actions in one
  season.
- *Global assignment* — every `(task, unit)` pair gets a cost of
  `priority × PRIO_WEIGHT + manhattan distance`. The whole board is assigned
  cheapest pair first. Letting each unit greedily choose its own nearest
  task looks equivalent, but it breaks ties by *unit index*, and that
  tie-break turned 9.9% of all moves into direct reversals. Costing the
  board globally makes the assignment depend on positions alone. Positions
  move only one tile a turn, so the assignment stays stable by construction.
- *Idle* — the unit stands still. Walking an idle unit home costs one move
  now and one move back when work appears. Hands respawn at the shed each
  morning anyway.

Assignment is now measured, and it is fixed. Moves that reverse the previous
move are 3% of all moves, against the 9.9% that global assignment cured. What
remains is trip length: the mean trip is 2.76 tiles late in the season, and
movement is 61% of all late-season actions. `PRIO_WEIGHT` is not the cause. A
sweep of 8, 11, 14 and 20 put every arm inside the noise band, and the best arm
landed exactly on the null. The trip length is geometry: the whole roster
services tasks spread over 75 tiles. Do not re-open this. Both figures were
measured on a 14-unit roster, before `MAX_HANDS` fell to 12.

## The strategy, in one page

Every constant in `main.py` carries a comment with the measurement behind it.
The load-bearing ones:

- **Strawberry is the engine.** It appears in 4 of the 8 shop kinds, the widest
  demand of any crop in the game. It is also `ongoing`: it is planted once and
  harvested four times. Measured yield is 7.07 units per planting, against the
  frontier's ~8. Fertilizer doubles 77% of production ticks, and no tick is
  ever missed for want of water.
- **`STRAW_TILES = 36` is a dead constant.** It never binds. Sweeping 30, 36,
  42 and 48 returned rewards identical to the dollar, so not one planting
  decision differed. `_roles` carves animals, melon and wheat first, and hands
  strawberry `rest[:STRAW_TILES]` from what survives. `len(rest)` is already at
  or below 36. To move strawberry acreage, move `ANIMAL_TILES`, `MELON_LATE` or
  `WHEAT_FRACTION` instead.
- **Wheat is a floor, not a plan** (`WHEAT_FRACTION = 0.38`). It is now the
  largest single crop on the board. Wheat is the only product in the game with
  a *log* glut curve: a full throughput unit dumped past equilibrium takes it
  from $25 to $20, and two units take it to $19. Strawberry and milk are linear
  ×1.6, wool is quadratic ×3.2, and melon is quadratic ×3.6, so all of them
  reach the $1 floor on a modest glut. Once the agent sells everything the
  moment it harvests, growing a crashable crop means crashing it ourselves. The
  constant moved 0.26 → 0.32 (119/120 and 120/120) after the sell block lost
  its restraints, then 0.32 → 0.38 (88/120 and 91/120) after `MELON_EARLY`
  tripled.
- **Do not raise `WHEAT_FRACTION`.** 0.41 scores 1/120 in-sample and **0/120**
  out-of-sample, two tiles above the adopted value. The obvious explanation was
  tested and refuted: `_roles` carves wheat before melon, so a higher fraction
  looks like it starves the opening melon block. Re-ordering the carve measured
  neutral at 62/120, and the cliff did not move. Past about 0.38 wheat simply
  displaces crops worth more, and the carve order only decides which crop pays.
  Re-sweep this after any change to `MELON_EARLY` or `HERD_CAP`.
- **Melon is a two-burst cash crop** (12 tiles fund the opening, 14 more go in
  on day 10, and the reservation stops on day 12). It has *no* shop demand at
  all. Its only consumer is the town center, so its whole season sink is about
  30 units, and it has no price floor. The opening block was 5 tiles, copied
  from the frontier. 12 wins 110/120 in-sample and **120/120** out-of-sample.
  The frontier spends its opening tiles on a day-3 strawberry ramp, and this
  agent spends its own on wheat, so the melon block no longer competes with the
  engine for the same ground.
- **Never buy a goose.** 298 cows, 155 sheep, and zero geese appeared across
  35 measured top-10 seasons. A goose yields 2 eggs a day from a $50 base
  cost. A cow yields 1.5 milk a day from a $160 base cost.
- **Small herd** (`HERD_CAP = 10`, `SHEEP_CAP = 4`). Above target, milk price
  falls linearly at ×1.6 and wool price falls quadratically at ×3.2.
  Overproducing crashes your own price. The cap fell twice this round: 14 → 12
  won 87/120, and 12 → 10 won a further 80/120 in-sample and 93/120
  out-of-sample. Two effects stack. Every animal costs a `FEED`, a `CARE` and a
  `COLLECT_FERTILIZER` every day, so two fewer animals return about 120 actions
  a season to crop work. The farm also stops crashing the two harshest price
  curves in the game. 8 is too few at 41/120. The frontier runs 13 animals, and
  the frontier also rations its sells.
- **Feed reserve doubles as a herd brake** (`FEED_DAYS = 4`). The agent grows
  the flock only while it can feed it this long, and it reserves that much feed
  money before it spends anything else. 3 → 4 won 94/120 in-sample and 91/120
  out-of-sample. The ridge is narrow: 5 still wins, and 6 collapses to 41/120,
  because past that the reserve starves the seed budget.
- **The hand roster is a Fibonacci bill** (`MAX_HANDS = 12`). A roster of `n`
  costs `fib(n+2)-1` *every day*: 10 hands cost $143, 12 cost $376, 14 cost
  $986, and 18 cost $6,764. The last figure bankrupts the farm, and 18 and 22
  both score **0/120**. 12 is a sharp peak at 116/120 and 117/120, against 14
  at 52/120. A coarse grid hides this, because sweeping 10, 14, 18 and 22
  straddles the peak. The ramp buys the roster out of income: 4 hands while
  broke, 10 from day 7, and the full 12 from day 10.
- **Plant late in the day** (`PLANT_HOUR = 22`). A new seed weeds over unless
  it is watered the same day, which is why a cutoff exists at all. The cutoff
  is now nearly worthless. Wheat covers a third of the board and replants
  continuously, so hours 21 and 22 are prime replanting time. 22 wins 111/120
  in-sample and 117/120 out-of-sample, and tightening is a catastrophe: 17 and
  14 both score **0/120**.
- **Land is a calendar, not a gate**: quadrant 2 unlocks on day 6, quadrant 3
  on day 10, and quadrant 4 never unlocks. This schedule follows from the
  strawberry income model — a version that copied the schedule without the
  income ramp scored only 5 wins in 48 games. Wheat dominance gave a reason to
  retest the fourth quadrant, so `LAND_DAY4` now exists as a sweepable scalar.
  It was a rout at every unlock day: 15/120 on day 12, 9/120 on day 16 and
  11/120 on day 20. $4,000 plus a fourth quadrant of walking is not repaid
  inside 30 days, whatever is planted on it.
- **Spend to the floor** (`CASH_RESERVE = 0`). On turn one, $3,000 buys five
  animals, ten seeds, and four hands, and the farm runs on $9 for two days
  afterward. The strategy keeps no reserve cash for emergencies within the
  30-day season. Re-confirmed this round: $150 scores 30/120 and $400 scores
  5/120.

## What this round settled, and what is left

The bare endgame board was the open lead. Between days 20 and 26, 20 to 34
tiles sat bare while 250 to 628 `PLANT_WHEAT` tasks a day went unexecuted.
Priced per unit-turn rather than per tile, strawberry returned about $21 and
wheat about $4, which argued for lapsing the strawberry reservation sooner.
`STRAW_STOP` was the direct test. It is dead flat on every arm, with an
identical worst case. The board did move, but `WHEAT_FRACTION` and the sell
block moved it, not the reservation calendar.

**A mechanism that explains a number is worth nothing until the intervention it
implies has been benchmarked.** Four mechanisms were proposed from plausible
reasoning and killed by measurement this round: `DIG` tiering, the unit-turn
economics above, "melon is crashable, so cut it", and the `_roles` carve order.
Three of the four sounded more convincing than the changes that actually won.

Where the agent stands, and what is still open:

| | value |
| :--- | :--- |
| vs the last committed agent | **119/120**, mean 84,558, worst 36,789 |
| mirror parity | 59/120 with 2 ties, mean 78,698, worst 41,305 |

1. **The wheat `keep`.** `keep = {"WHEAT": n_animals + 10}` is the only sell
   restraint left, and it has never been swept. It is a hardcoded expression,
   so extract a scalar first. A 10-animal herd reserves 20 wheat.
2. **The constants not yet re-measured on the current agent**:
   `PROJ_FRACTION`, `WATER_PRIO`, `SHEEP_CAP`, `MELON_WAVE2` and `HANDS_DAY2`.
3. **Benchmark against an opponent outside this lineage** before submitting.
   Every measurement here is against our own immediate predecessor, and in a
   shared-market game A can beat B while doing worse than B against C.

## Measuring a change

```sh
python3 test_agent.py                       # invariants; no deps needed
.venv/bin/python play.py starter 7 watch    # one season + replay.html
.venv/bin/python bench.py baseline.py       # 120 games vs the frozen previous version
.venv/bin/python bench.py baseline.py WHEAT_FRACTION=0.32,0.38,0.41   # sweep against it
.venv/bin/python validate.py                # determinism, parity, seat balance
```

Always benchmark side by side against `baseline.py`. When a change wins, copy
`main.py` over `baseline.py`, and start the next round against that. Never
measure in self mode. `bench.py self` re-reads `main.py` from disk for both
seats, so both seats change together and the win rate stays pinned at half by
construction. Self mode cannot measure a logic edit, and it cannot measure a
constant either once the baseline has moved.

Five rules the harness exists to enforce:

1. **Rank on wins, never on mean.** A mirror match still swings by ±$19,600
   per game, because one extra planted tile reshuffles the shared random
   seed. `LAND_USE=2.0` earned 52k against the default's 59k, but it won only
   3 games of 48. Producing less leaves market room that the opponent can
   sell into. A mirror season can also end at $776, so a sub-$1k worst case is
   a property of the matchup, not evidence against the candidate.
2. **Read a candidate against 60/120.** The mirror of the current agent wins
   59/120 with 2 ties. Ties count as losses, and a change in behavior breaks
   the ties. So the null for a candidate is `(120-0)/2 = 60`. The old 57/120
   reference is obsolete. Anything inside about ±10 wins is noise.
3. **Sweep past the candidate.** Peaks here are sharp, not broad.
   `WHEAT_FRACTION` at 0.41 scores 1/120, and `STRAW_PLANT_PRIO` at tier 4
   scores 19/120. A neighbor that collapses is the signal that the sweep is
   sound. A control arm that reproduces mirror parity is the other one. Every
   large win this round sat at the edge of its first grid, and every one moved
   when the grid was extended.
4. **Confirm on out-of-sample seeds.** `validate.py` holds a disjoint seed set.
   Every adopted change in rounds 4 and 5 won on both sets independently.
5. **A constant that sweeps flat is either inert or optimal. Find out which.**
   `STRAW_TILES` and `ANIMAL_TILES` are capped by other constants and can never
   bind. `PRIO_WEIGHT` and `STRAW_STOP` do bind, and they simply do not matter.
   The first pair is a code defect. The second pair is information.

`bench._run` raises an error if you sweep a name that `main.py` does not
define. Without this check, a dead `setattr` would silently measure one
config N times and report it as a valid comparison. This happened once, and
it cost one benchmark round of wasted work.

One trap worth knowing when you instrument a run:
`env.run([main.agent, main.agent])` gives both seats the same wrapped function.
Any spy must gate on `obs["player"]`, or every count is doubled.

---

# Game rules reference

Everything below is the environment specification. It describes the rules
that `main.py` plays against, not the agent itself. Kaggriculture is a
farming simulation where two players compete to earn the most income by
selling farm goods into a dynamic market.

This document is verified against **kaggle-environments 1.32.6**, the
version the competition runs. Check this version stamp before you trust any
number here. An earlier round of tuning used version 1.32.4, which had
different town-demand rules, and every constant that round produced had to
be discarded.

## Overview

Each player starts with an empty farm and a small amount of starting money.
The game runs for a fixed length of time, representing one season, and the
player with the most money in the bank at the end wins.

Each turn, a player can:

- move around the board
- buy seeds or livestock
- plant seeds
- water plants
- harvest produce or animal products
- sell produce at the market

## Object Types

| Type | Yield Type | Seed Cost | Base Market Price | Time to First Yield | Time to Max Yield | Subsequent Yields | Max Yield | Action Cost | Yield / tile / day |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| **Wheat** | One-time | 10 | 25 | 2 days | 4 days | none | 6 (4 unfertilized) | 1 | 0.80 |
| **Carrot** | One-time | 20 | 35 | 2 days | 3 days | none | 4 (3 unfertilized) | 1 | 0.75 |
| **Tomato** | Ongoing | 50 | 60 | 8 days | 11 days | every day ×4 | 4 | 1 | 0.33 |
| **Strawberry** | Ongoing | 100 | 120 | 10 days | 16 days | every other day ×4 | 4 | 1 | 0.24 |
| **Melon** | One-time | 80 | 250 | 10 days | 10 days | none | 6 | 1 | 0.55 |
| **Goose/Egg** | Ongoing | 300 | 50 | 4 days | NA | every day, indefinitely | 4 held | 1 \+ 1 (build coop) | 1.00 |
| **Cow/Milk** | Ongoing | 400 | 160 | 8 days | NA | every two days, indefinitely | 6 held | 1 \+ 1 (build pasture) | 0.50 |
| **Sheep/Wool** | Ongoing | 500 | 200 | 6 days | NA | every three days, indefinitely | 6 held | 1 \+ 1 (build pasture) | 0.33 |
| **Fertilizer** | NA | 100 | X |  | X | X |  | 1 |  |

For crops, "Yield / tile / day" is the total units harvested, divided by the
days the tile is occupied, assuming daily watering and harvest at peak
yield. For animals, it is the steady-state production rate (`1 / interval`)
once the first yield lands. Animals keep producing for as long as they are
fed, so there is no fixed occupancy period to divide by. For animals, "Max
Yield" means `max_held`: the cap on *unharvested* product sitting on the
tile, not a lifetime total.

Crop "Time to Max Yield" is the age at which yield stops increasing under
daily watering. This age is not always the end of the bonus window:

- **Melon**'s bonus window is ages 6–12. But the base of 1 unit, plus one
  unit per watered day, reaches the cap of 6 at age 10, so ages 11–12 add
  nothing. Fertilizing reaches the cap earlier, at age 8.
- **Wheat** and **Carrot** reach their listed Max Yield of 6 and 4 only with
  fertilizer. Watering alone peaks at 4 and 3.
- **Tomato** and **Strawberry** are ongoing crops, but they are *not*
  indefinite. Production is capped at 4 scheduled yields: tomato at ages
  8–11, and strawberry at ages 10, 12, 14, and 16. After the 4th yield, the
  plant decays into a weed.

The player must water every plant every day, or it becomes a weed after two
successive days without water. The player must feed every animal every day
using wheat, or it escapes and becomes unrecoverable after two successive
days without food. Players can also buy wheat at the market, at the current
market price.

## Actions

Each turn, the player may take one action. There are 24 turns per day and 30
days in the season — 720 total turns.

### Farmer / Farm Hand Action

Each farmer or farm hand can be given an action every turn. A farmer and a
farm hand can occupy the same space.

#### Movement

- `NORTH`, `SOUTH`, `EAST`, `WEST` — move one cell in that direction. A move
  off the edge of the board does nothing. Locked tiles are passable: a unit
  may move onto and across unbought quadrants. But tile actions (`PLANT`,
  `WATER`, `BUILD_*`, and others) do nothing on a locked tile and consume no
  resources.

#### Shed

- `PICKUP` `<item>` `[n]` — move up to `n` units of `<item>` (default 1)
  from the shed into the active farmer or hand's inventory. Any item present
  in the shed is valid: animals, fertilizer, harvested produce, and others.
  Seeds live in a separate slot. `PLANT` consumes seeds directly. `PICKUP`
  never moves them.
- `DROP` — when standing orthogonally adjacent to the shed, this action
  moves the active farmer or hand's entire inventory into the shed. Any
  overflow past `shedCapacity` is discarded. The action does nothing if the
  unit is not shed-adjacent.

#### Plants

- `PLANT` — plant a seed bought earlier from the market.
  - Seeds are automatically available to all farmers and farm hands.
  - If a turn tries to plant more seeds of one kind than the shed holds,
    none of them are planted. Example: the shed has 1 melon seed, but two
    units both issue `PLANT MELON` in the same turn. Neither planting
    happens.
- `WATER` — water a plant. This needs doing only once per day. A second
  watering on the same day does nothing.
- `HARVEST` — gather produce from a plant. If the plant has no further
  scheduled yields, harvest removes it from the map. Each harvest yields at
  least one unit of the crop, plus a possible bonus from watering and
  fertilizer. The bonus formula differs by crop type. See Harvest Yields
  below. Harvested items go into the inventory.
- `FERTILIZE` — fertilize a plant to raise its potential yield (see Harvest
  Yields below).
  - This doubles the per-day yield bonus for the next 3 days. The bonus
    applies only on days when the plant is also watered — basic needs come
    first.

#### Animals

- `PLACE` `<item>` `[n]` — move items from the active farmer or hand's
  inventory onto a tile or into the shed:
  - **Animal placement**: when a unit stands on a matching unoccupied
    structure (`GOOSE` on a coop, `SHEEP` or `COW` on a pasture), `PLACE`
    moves one animal from inventory onto the tile. The `n` argument is
    ignored.
  - **Shed drop**: when a unit stands orthogonally adjacent to the shed,
    `PLACE` moves up to `n` (default 1) of `<item>` from inventory into the
    shed. `shedCapacity` caps this. Any excess stays in inventory.
- `FEED` — feed an animal using wheat. This needs doing only once per day.
- `HARVEST` — collect the eggs, milk, or wool the animal has produced.
- `COLLECT_FERTILIZER` — collect 1 fertilizer unit from the animal. Every
  surviving animal makes 1 unit available at the end of each day, whether or
  not it was fed or cared for that day. Uncollected fertilizer does not
  accumulate: an animal left alone for five days still yields only 1 unit
  when collected.
- `CARE` — care for an animal. This needs doing only once per day. A second
  `CARE` on the same day does nothing. See Animal Care below.

#### Animal Care

`CARE` banks a yield bonus. The environment pays this bonus out on the
animal's next scheduled production:

- At the end of each day, if the animal was both fed and cared for that day,
  `pending_care_bonus` increases by 1. A day when the animal went unfed
  banks no bonus — basic needs come first.
- On a scheduled production day, if the animal is fed, production adds the
  entire banked bonus to the base yield of 1, then resets the bank to 0.
- On a scheduled production day, if the animal is unfed, production still
  yields the base 1 unit, but it does not apply the banked bonus. The bank
  still resets to 0.
- The per-animal `max_held` cap on `yield_units` indirectly caps
  `pending_care_bonus`.

#### Terrain

- `BUILD_COOP` — adds a coop to an unoccupied tile.
- `BUILD_PASTURE` — adds a pasture to an unoccupied tile.
- `DIG` — removes a plant from a tile to free the space, or removes a weed
  from a tile (this yields no produce), or removes an **empty** goose coop
  or pasture. `DIG` does nothing to a coop or pasture that has an animal on
  it.

#### Other

- `PASS` — default action if there is nothing to do (optional).

### Market Action

Each turn, a player can submit up to `maxMarketOrdersPerTurn` (default 10)
market actions. The environment silently drops any orders past that limit.
Market orders form an ordered list. The environment processes them in order,
simultaneously for both players, one order from each player at a time, for
as long as both players still have orders.

- `BUY_SEED` — buy N units of a single seed item from the market.
  - Example: `BUY_SEED WHEAT 1`
- `BUY_ANIMAL` — buy N units of a single animal from the market.
  - Example: `BUY_ANIMAL GOOSE 1`
- `BUY_PRODUCT` — buy N units of wheat or fertilizer from the market.
  - Example: `BUY_PRODUCT WHEAT 1`
  - Example: `BUY_PRODUCT FERTILIZER 1`
- `SELL` — sell N units of a single item to the market.
  - Example: `SELL WHEAT 1`
- `HIRE` — hire a farm hand for the day. The cost increases for each extra
  hand hired the same day.
- `BUY_LAND` — unlock a new 5×5 segment of land to plant on. The cost
  increases with each purchase: $1k, then $2k, then $4k.

## Watering / Animal Feed

The player must water plants and feed animals at least every other day.
Watering needs doing only once per day. A later watering action on the same
day does nothing. A plant left unwatered for two consecutive days becomes a
weed at the end of the second day. An animal left unfed for two consecutive
days escapes, and it cannot be recovered.

A new seed starts with `consecutive_unwatered = 1`. The planting day itself
counts as the first missed day. If a seed is planted and left unwatered that
same day, its counter reaches 2 at the end-of-day refresh, and it becomes a
weed that night, before it has a chance to grow. Fresh plantings get no
grace period.

A newly placed animal starts with `consecutive_unfed = 0`, so it survives
its first day unfed.

Watering a one-time-yield plant during its yield window raises its yield.
This is not true for ongoing-yield plants or animals. See Harvest Yields
below.

## Harvest Yields

A plant's yield can rise above the base amount, depending on how well the
player cares for it.

- **One-time crops** (wheat, carrot, melon): the bonus window starts at half
  the plant's `max_yield_day` (Time to Max Yield), rounded up. Watering
  during this window adds one unit per day to the total harvestable yield.
  - A fertilized plant adds 2 units per day instead of 1.
- **Ongoing crops** (tomato, strawberry): scheduled production happens at
  fixed intervals. The base yield is 1 unit per scheduled production. If the
  plant is both fertilized and watered that day, the yield doubles to 2
  units.
- Once a plant reaches its maximum lifespan, its total available yield falls
  by 1 unit every other turn until it reaches 0. At that point the plant
  becomes a weed.
  - **One-time crops** reach maximum lifespan one day after `max_yield_day`.
  - **Ongoing crops** start to decay one day after their cumulative
    production count reaches `max_yield`. That is, once they have fired
    enough scheduled productions to hit the cap, decay starts regardless of
    whether the produce has been harvested.

## Map Features

Each player has a farm with a fixed number of squares. A player cannot see
the opponent's shed, but can see the opponent's farm.

### Farm Space

- The farm is a `boardSize` × `boardSize` grid (default 10×10), divided into
  four 5×5 quadrants. At the start, the player's farm covers one quadrant,
  25% of the squares. The player can buy the neighboring quadrants for an
  increasing fee, up to 100% of the squares.
- Each plant or animal occupies one square on the farm.
- The player can assign these squares to crops or livestock in any mix. No
  per-type limit applies.
- A weed may spawn on any empty square on the farm. The player must clear a
  weed before using that square for anything else.
- Each square on the farm holds one of: a plant, a coop or pasture, a weed,
  or nothing.

### Shed (Inventory)

- The shed works as an inventory. It holds items already harvested but not
  yet sold, and seeds not yet planted.
- The farmer and any hired farm hands spawn at the shed at the start of each
  day.
- The farmer and hired farm hands drop their inventory into the shed at the
  end of the day, if room allows.
- The shed holds at most 100 items, not counting seeds. Once the shed is
  full, the environment discards any further items added, whether by a
  mid-day `PLACE` or the end-of-day inventory drop. No overflow storage
  exists, so holding items in a farmer's or hand's inventory does not
  bypass this cap.
- `DROP`, `PICKUP`, and `PLACE` resolve **before** the `LOCKED` tile check.
  So all four shed-access tiles work from turn 0, even though three of them
  sit in locked quadrants. Every other tile action still does nothing on a
  `LOCKED` tile.

The shed sits at the center of the board. It is not a tile: it never appears
in the `tiles` array, whose only values are `None`, `"LOCKED"`, and
structure dicts. "Orthogonally adjacent to the shed" means standing on one
of the four center tiles: `(half-1, half-1)`, `(half, half-1)`,
`(half-1, half)`, `(half, half)`, for `half = boardSize // 2`. At the
default `boardSize = 10`, those tiles are `(4,4)`, `(5,4)`, `(4,5)`, and
`(5,5)`, one tile in each quadrant.

### Farmer/Farm Hand

#### Hiring

- Hiring is a market order (`HIRE`). Each additional hand hired the same day
  costs more than the last. At the end of the day, every hand drops its
  inventory at the farm and disappears. The player must hire a hand again on
  any day it is needed.
- The cost is `farmHandCostMult * fib(n)`, where `n` is the number of hires
  already made that day. (The Fibonacci sequence starts 1, 1, 2, 3, 5, 8,
  13, and so on.)
  - With the default `farmHandCostMult = 1`, the costs run 1, 1, 2, 3, 5, 8,
    13, 21, and so on. This sequence resets at the start of each day.
- A hired hand appears orthogonally adjacent to the shed, in a free space,
  checked in north-west-south-east order. If no space is free, the hand
  spawns in the space with the fewest occupants, again breaking ties in
  north-west-south-east order.
- Spawn placement ignores whether the tile is locked. Because the main
  farmer starts on `(4,4)`, the least-occupied rule sends the first hire of
  each day to `(5,4)`, a tile locked until the player buys the NE quadrant.
  Locked tiles are passable, so a hand that spawns on one can still move
  back to unlocked land.

#### Inventory

- Harvesting or picking up an item adds it to the unit's inventory.
- A unit can drop items into the shed.
- At the end of the day, the environment moves every item from every
  inventory into the shed, if room allows. Anything that does not fit is
  discarded, and the overflow is lost.

### Town Buildings

As the season progresses, new shops unlock at regular intervals: every
`townShopUnlockInterval` days, default 3. Each unlock draws **with
replacement** from the full shop list. So the same shop can unlock more than
once, and each copy consumes stock independently — this draw method does
not guarantee variety. Only the total instance count is capped, at
`MAX_SHOP_INSTANCES = 8`. Once unlocked, a shop stays active for the rest of
the game, so total demand rises steadily until it hits the cap. (Before
version 1.32.6, the draw was without replacement, so the game always
produced 8 distinct shops.)

Each unlocked shop consumes one unit of every product it demands, every
`townShopSellInterval` turns (default 4). So with the default interval, a
shop that demands wheat removes 6 units of wheat from the market each day. A
single-product shop consumes at double this rate.

The town center also consumes one unit of every product, excluding
fertilizer, every `townCenterSellInterval` turns (default 24, once a day).
Demand is **flat, at 1 unit per product per tick, for the whole season**. It
does not scale with the calendar. Before version 1.32.6, the interval was 12
turns (twice a day), and a demand schedule doubled it after day 10 and
quadrupled it after day 20. This made late-season town-center demand 8 units
a day, where it is now 1 unit a day. Any strategy that relies on late-game
town demand was tuned to a version of the game that no longer exists.

| Shop Type | Increases Demand For |
| :---- | :---- |
| Bakery | eggs, wheat  |
| Pizza Shop | milk, tomatoes, wheat |
| Brunch Spot | eggs, wheat, strawberries |
| Yarn Store | wool (2x) |
| Ice Cream Shop | strawberries, milk, wheat |
| Pet Cafe | carrots (2x) |
| Smoothie Shop | strawberries, milk |
| Farmers Market | wheat, carrots, tomatoes, strawberries |

## Market Mechanics

The market has an unlimited supply of seeds and animals, at fixed prices.
Sell prices, in contrast, move dynamically for each resource, and they
persist across days.

Every product, and fertilizer, starts the game with a market inventory of
`I0 = 10,000` units. This is far above any single game's realistic
production volume, so inventory stays positive for practical purposes. The
sell price for a product equals `base` when inventory is at `I0`. Price
rises as inventory falls, whether from player buying or from town
consumption draining supply. Price falls as inventory grows from player
selling.

### Selling inventory to the market

A player can queue any number of sell or buy orders, of any quantity, in the
market action list. The environment processes orders concurrently across
players, one unit at a time. Example: both players issue `SELL CARROT 10`
as their first order. The environment takes the current carrot price and
pays both players that price for their first carrot. It then adds 2 carrots
to the market, 1 from each player, which may shift the price. It repeats
this process until both orders complete.

If selling has driven the price down to `$1`, the price floor, the
environment still buys the unit from the player, but does not add it to
market inventory. This keeps the floor responsive to later buy orders.

### Buying inventory from the market

A player can buy only `WHEAT` and `FERTILIZER` from the market, using
`BUY_PRODUCT`. The market sells other products but does not buy them back.
Selling has no such restriction: a player can sell any product, including
fertilizer collected from animals, using `SELL`. Two things drain market
inventory: town buildings (the town center and shops, which consume
products at no cost) and player `BUY_PRODUCT` orders. Buy orders follow the
same one-unit-at-a-time concurrent procedure as sell orders. If a player
runs out of money partway through an order, the environment stops that
order at that point.

The environment quotes the buy price at the post-buy inventory level. It
quotes the sell price at the pre-sell inventory level. So an immediate buy,
followed by a sell of the same item, against an otherwise unchanged market,
nets exactly zero.

### The Price Function

For each resource, the price curve is defined by a base price, an anchor
throughput `T`, and an independent **shape function** and **target move**
for each side of the equilibrium:

```
price(inv) = base + sign · amp · f(|inv − I0|)
  sign = +1  if inv < I0   (scarcity → price up)
  sign = −1  if inv > I0   (glut    → price down)
  amp  = target · base / f(T)        (derived; not stored)
  f    ∈ { linear, sq, sqrt, log, log10 }   (log uses ln(1+x), so f(0)=0)
```

The price is floored at `$1` and rounded to the nearest dollar.

`T` is the production capacity of a single 5×5 field over a 24-day window,
at optimal watering, with no fertilizer. Animal totals are pre-discounted by
30% to account for wheat-feed overhead, and to allow one day to build the
coop or pasture. The 24-day window is a calibration horizon, not the 30-day
season length. It is shorter on purpose, because the opening days are
setup-heavy and yield little.

`target` means: moving `T` units past `I0` shifts the price by
`target × base`. Picking a different `f` and `target` on each side lets
resources with similar production profiles behave very differently in
strategy. Wheat panics on scarcity but absorbs gluts easily. Carrot does the
opposite. Melon barely reacts to scarcity but crashes hard on
overproduction. Wool mirrors melon's pattern at a smaller scale. Premium
resources — base price above $100: strawberry, melon, milk, wool — use
`above_target > 1`, so even a modest glut drives their price straight to the
$1 floor. For these resources, bundling and timing sales matters more than
it does for staple resources.

| Resource | Base | I0 | T | Below func | Below target | Above func | Above target | P(I0−T) | P(I0+T) | P(I0+2T) |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| **Wheat** | 25 | 10,000 | 400 | sqrt | 0.80 | log | 0.20 | $45 | $20 | $19 |
| **Carrot** | 35 | 10,000 | 450 | log | 0.20 | sqrt | 0.70 | $42 | $10 | $1 |
| **Tomato** | 60 | 10,000 | 200 | linear | 0.40 | sqrt | 0.60 | $84 | $24 | $9 |
| **Strawberry** | 120 | 10,000 | 100 | sqrt | 0.70 | linear | 1.60 | $204 | $1 | $1 |
| **Melon** | 250 | 10,000 | 300 | log | 0.20 | sq | 3.60 | $300 | $1 | $1 |
| **Egg** | 50 | 10,000 | 332 | linear | 0.40 | log | 0.20 | $70 | $40 | $39 |
| **Milk** | 160 | 10,000 | 122 | sqrt | 0.60 | linear | 1.60 | $256 | $1 | $1 |
| **Wool** | 200 | 10,000 | 105 | log | 0.20 | sq | 3.20 | $240 | $1 | $1 |
| **Fertilizer** | 100 | 10,000 | 200 | linear | 0.40 | linear | 0.40 | $140 | $60 | $20 |

The defaults live in `MARKET_PARAMS` in `kaggriculture.py`. A caller can
supply per-resource overrides — a sparse subset of `base`, `I0`, `T`,
`below_func`, `below_target`, `above_func`, `above_target` — at episode
creation, via `env.configuration["marketParams"]`, without changing code.
Example: `{"WOOL": {"above_target": 0.95}}`.

## Turn Processing Order

1. **Action validation** — check that each submitted action is legal.
2. **Player actions** — record the actions each player took. Both players'
   actions happen simultaneously.
3. **Market actions** — process the market queue in order, by player, as
   described above.
4. **Town buy actions** — the town center and shops reduce market
   inventory.
5. **Update observations**:
   - **Day refresh** — on a new day, update the condition of plants and
     animals, and reset their fed and watered status to false.
   - **Market refresh** — adjust the price of items on the market, based on
     the previous turn's sells.
   - **Income update** — update each player's bank balance, based on any
     buys or sells.
   - **Farm update** — clear harvested plants and used or sold inventory
     items, add new plants or animals to the farm, and apply other
     end-of-turn changes.

## Win Conditions

The win condition is simple: the player with the most coins at the end of
the season wins. A tie between the two players is also possible.

## Reward

The player who has the most money in the bank at the end of the game wins.
Unsold items in the inventory do not count toward that total.

## Observation Format

The top-level observation passed to each agent:

```py
{
  "player": int,           # 0 or 1
  "day":    int,           # 0-indexed in-game day
  "hour":   int,           # 0-indexed turn within the day
  "farms":  [farm, farm],  # public per-player state, indexed by player id (shared)
  "market": {              # shared
    "inventory": { "WHEAT": int, "CARROT": int, ... },
    "prices":    { "WHEAT": int, "CARROT": int, ... },
  },
  "town": {                # shared
    "unlocked_shops": ["BAKERY", ...],
  },
  "private": {             # this player only. Opponent's private state is not visible
    "shed":        { "WHEAT": int, "GOOSE": int, "FERTILIZER": int, ... },
    "seeds":       { "WHEAT": int, "CARROT": int, ... },
    "inventories": [farmer_inv, hand_inv, ...],  # [0] is the main farmer
  },
}
```

Each `farm` dict (public, visible to both players):

```py
{
  "money":              float,
  "tiles":              [[tile, ...], ...],   # tiles[y][x]
  "farmer":             [x, y],
  "hands":              [[x, y], ...],         # hired hands for the current day
  "unlocked_quadrants": ["NW", ...],          # subset of {"NW","NE","SW","SE"}
  "hires_today":        int,                  # used to price the next HIRE
}
```

A `tile` is one of:

- `None` — empty unlocked tile
- `"LOCKED"` — tile in a quadrant the player has not yet bought
- a plant dict:
  ```py
  {
    "kind":                 "PLANT",
    "crop":                 "WHEAT" | "CARROT" | "TOMATO" | "STRAWBERRY" | "MELON",
    "planted_day":          int,
    "watered_today":        bool,   # reset to False each end-of-day
    "consecutive_unwatered": int,   # 2+ → tile becomes a weed
    "yield_units":          int,    # units currently harvestable
    "max_lifespan_step":    int,    # step at which decay begins (-1 for ongoing crops)
    "fertilized_until_day": int,    # last day fertilizer bonus applies (-1 if none)
  }
  ```
- a weed dict: `{"kind": "WEED"}`
- an animal structure dict (coop/pasture, optionally occupied):
  ```py
  {
    "kind":                 "COOP" | "PASTURE",
    "animal":               "GOOSE" | "COW" | "SHEEP" | None,  # None until PLACEd
    "placed_day":           int,
    "yield_units":          int,
    "fed_today":            bool,
    "consecutive_unfed":    int,    # 2+ → animal escapes
    "cared_today":          bool,
    "fertilizer_available": bool,   # set at end-of-day for every surviving animal (cleared by COLLECT_FERTILIZER)
    "pending_care_bonus":   int,    # banked CARE bonus, applied on the next yield tick
  }
  ```

## Quick Start

```py
from kaggle_environments import make


def my_agent(obs):
    # Buy one wheat seed on the very first turn, then PASS forever after.
    if obs.get("step", 0) == 0:
        return {"farmer": ["PASS"], "market": [["BUY_SEED", "WHEAT", 1]]}
    return {"farmer": ["PASS"], "market": []}


env = make("kaggriculture", configuration={"episodeSteps": 200})
env.run([my_agent, "random"])
env.render(mode="ipython", width=800, height=800)
```

## Configuration Defaults

Per-crop seed costs and per-product base prices are not configurable. They
are documented in the Object Types and Price Function tables above. The
configurable knobs are:

| Parameter | Default | Description |
| :---- | :---- | :---- |
| episodeSteps | 720 | Total turns in the season (24 turns × 30 days) |
| boardSize | 10 | Width and height, in tiles, of each player's square farm. The default of 10 gives four 5×5 quadrants |
| startingMoney | 3000 | Starting coin balance for each player |
| maxMarketOrdersPerTurn | 10 | Maximum number of market orders processed per player per turn. The environment silently drops any extra orders |
| turnsPerDay | 24 | Number of turns in one in-game day |
| shedCapacity | 100 | Maximum non-seed items the shed can hold. The environment discards overflow at the end-of-day drop |
| weedSpawnChance | 0.005 | Per-tile probability of a weed spawning on an empty unlocked tile during end-of-day refresh |
| townShopUnlockInterval | 3 | Days between successive town shop unlocks |
| townShopSellInterval | 4 | Turns between consumption ticks by every unlocked town shop |
| townCenterSellInterval | 24 | Turns between consumption ticks by the town center — once a day by default. Before version 1.32.6, this was 12 turns, twice a day |
| farmHandCostMult | 1 | Multiplier on the Fibonacci hire cost. The `n`th hire of the day costs `farmHandCostMult * fib(n)` |
| marketParams | {} | Sparse per-resource overrides of the price-function parameters (see The Price Function) |
| seed | null | Optional input seed for deterministic episode generation. The environment clears it from the config after reading it, so it stays out of agent observations |
