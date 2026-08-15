# Kaggriculture agent

A submission for the Kaggriculture competition (two-player farming sim, 30 days ×
24 turns, most money wins) plus the harness used to measure changes to it.

`main.py` is the whole submission: one `agent(obs)` function, stdlib only
(`math`, `collections`), no state carried between turns. Everything else in the
repo exists to answer "did that edit actually help?"

The game rules themselves are in the second half of this file.

## Files

| Path | What it is |
| :--- | :--- |
| `main.py` | The agent. This is the file that gets submitted. |
| `baseline.py` | Frozen copy of `main.py`. The head-to-head opponent for benchmarking a *logic* edit. Currently byte-identical to `main.py`. |
| `bench.py` | 60 seeds × 2 seats = 120 games in parallel; optionally sweeps constants. |
| `validate.py` | Checks the benchmark itself: determinism, true parity, seat balance, out-of-sample. |
| `play.py` | One episode, day-by-day table, optional `replay.html`. |
| `test_agent.py` | Dependency-free smoke test on invariants (legal actions, order caps). |
| `frontier-summary.json` | Per-day summaries distilled from top-10 leaderboard replays; the strategy in `main.py` was fitted to these. |

## How the agent decides a turn

`agent(obs)` runs the same pipeline every one of the 720 turns. It is stateless:
everything is re-derived from the observation, so there is no per-unit target or
plan to keep in sync.

**1. Census.** Count the herd, empty structures, unfed animals, and `pending` —
animals bought but not yet standing on a tile, counting both the shed *and* unit
inventories.

**2. Capacity gate.** `capacity = min(HERD_CAP, herd + affordable)`, where
affordable is `spendable // (wheat_price * FEED_DAYS)`. Cash binds the flock, not
tiles: feed is bought, not grown, and a starved animal is a total loss. `pending`
is exempt from the gate — it throttles *buying*, and must never refuse to house
stock already paid for.

**3. Price projection** (`_projected`). Re-implements the environment's price
curve and evaluates each animal product at a half-season horizon, given the herds
standing on *both* boards and the drain from unlocked shops. A cow's milk doesn't
reach the market for 8 days, so ranking on today's spot price fills every pasture
with one species before any feedback arrives. `_best_species` then picks cow vs
sheep by `RATE × projected price`, which self-balances: each cow bought drops
projected milk and rotates the next buy to wool.

**4. Tile roles** (`_roles`). Every unlocked tile gets one role, handed out as
*ordered lists*:

- `ANIMAL` — the innermost tiles by distance from the shed, including the four
  shed-adjacent tiles (a pasture built there is fed at zero walking cost).
- Crops — sorted by `(quadrant, distance)`, **not** distance alone. Pure distance
  sorting hands each crop a ring whose consecutive tiles sit on opposite edges of
  the board; blocking by quadrant gives contiguous slabs and cut the mean walk
  before a productive action from 3.70 tiles to 1.19.

Reservations *expire*, and that expiry is the endgame plan: melon's lapses on day
14 and strawberry's on day 12, so as those plants are harvested or decay their
tiles fall through to wheat with no special-case code.

**5. Task list** (`_tasks`). Emits `(priority, x, y, op)` for all outstanding
work. Priorities are **fixed tiers, not dollar values** — pricing tasks off live
market prices was tried and scored 17k against this version's 37.5k, because a
$1,500 melon harvest reliably outbids a $250 FEED and the flock starves.
Deadlines drive this game; feeding is worthless tomorrow.

| Prio | Ops |
| :--- | :--- |
| 0 | `FEED` an animal that missed yesterday (dies tonight) |
| 1 | `HARVEST` at the yield cap, `PLACE` an animal on a matching structure |
| 2 | `FEED`, `BUILD_PASTURE` while animals wait in the shed |
| 3 | `WATER` a plant that weeds over tonight or produces tonight |
| 4 | `CARE` (one care on a cow is worth a whole $336 milk) |
| 5 | `FERTILIZE`, `COLLECT_FERTILIZER`, `WATER` for the yield bonus |
| 6 | `BUILD_PASTURE` normally, ordinary `HARVEST` |
| 7 | `PLANT`, `DIG` a weed |

**6. Market orders**, in a fixed spend order, truncated to the 10 that clear per
turn: buy feed wheat → `HIRE` (ramped, cost is `fib(n)` per day) → `BUY_LAND` on
the calendar → animals → seeds → sells. Each stage subtracts from `spendable`, so
the feed reserve is held back before strawberry at $100 a tile can drink it.
Sells drip out in chunks of 5 and refuse to go below `SELL_FLOOR`, except when
the shed is crowded, the season is ending, or the opponent's public board shows
`RIVAL_DUMP` units about to land.

**7. Unit assignment**, three passes:

- *Shed work* — a unit standing on a shed tile banks produce, restocks wheat,
  picks up an animal there's somewhere to put, or takes fertilizer out to the
  field. Wheat, animals and fertilizer are never dropped: `DROP`/`PICKUP` of
  working stock is an infinite loop that once burned 962 actions a season.
- *Global assignment* — every `(task, unit)` pair is costed as
  `priority × PRIO_WEIGHT + manhattan distance` and the whole board is assigned
  cheapest-first. Letting each unit greedily grab its own nearest task looks
  equivalent but breaks ties by *unit index*, which turned 9.9% of all moves into
  direct reversals. Costing globally makes the assignment a function of positions
  alone, and positions move one tile a turn, so it's stable by construction.
- *Idle* — stand still. Walking an idle unit home costs a move now and a move
  back when work appears; hands respawn at the shed each morning anyway.

## The strategy, in one page

Every constant in `main.py` carries a comment with the measurement behind it.
The load-bearing ones:

- **Strawberry is the engine** (`STRAW_TILES = 36`). It appears in 4 of the 8
  shop kinds — the widest demand in the game — and is `ongoing`: planted once,
  harvested four times.
- **Melon is a two-burst cash crop** (5 tiles to fund the opening, 14 more on day
  10). It has *no* shop demand at all; its only consumer is the town centre, so
  its whole season sink is ~30 units and there is no price floor on it.
- **Never buy a goose.** 298 cows, 155 sheep and zero geese across 35 measured
  top-10 seasons. A goose is 2 eggs/day off a $50 base against a cow's 1.5 milk
  off $160.
- **Small herd** (`HERD_CAP = 14`, `SHEEP_CAP = 4`). Milk is linear ×1.6 and wool
  quadratic ×3.2 above target; overproducing crashes your own price.
- **Land is a calendar**, not a gate: quadrant 2 on day 6, quadrant 3 on day 10,
  quadrant 4 never. The schedule is downstream of the strawberry income model —
  copying it without the ramp scored 5/48.
- **Spend to the floor** (`CASH_RESERVE = 0`). $3,000 becomes five animals, ten
  seeds and four hands on turn one, and the farm runs on $9 for two days. There
  is no rainy day inside 30 turns.

## Measuring a change

```sh
python3 test_agent.py                       # invariants; no deps needed
.venv/bin/python play.py starter 7 watch    # one season + replay.html
.venv/bin/python bench.py                   # 120 games vs an unswept copy of main.py
.venv/bin/python bench.py baseline.py       # 120 games vs the frozen previous version
.venv/bin/python bench.py self WHEAT_FRACTION=0.20,0.26,0.32   # sweep a constant
.venv/bin/python validate.py                # determinism, parity, seat balance
```

Three rules the harness exists to enforce:

1. **Rank on wins, never on mean.** A mirror match still swings ±$19,600 per game
   because one extra planted tile reshuffles the shared RNG. `LAND_USE=2.0` earned
   52k against the default's 59k while winning 3 games of 48 — producing less
   leaves market capacity for the opponent to sell into.
2. **A sweep can only measure a constant.** `bench.py self` re-reads `main.py` off
   disk, so both seats change together and the win rate is pinned at half. To
   measure a *logic* edit, freeze the version you want to beat
   (`cp main.py baseline.py`) and bench against the file.
3. **Parity is 57/120, not 60/120.** Anything under roughly ±6 wins is noise;
   confirm adopted changes on the disjoint seed set in `validate.py`.

`bench._run` raises if you sweep a name `main.py` doesn't define — a dead
`setattr` silently measures one config N times and prints it as a comparison,
which happened once and cost a round.

---

# Game rules reference

Everything below is the environment spec — the rules `main.py` plays against,
not a description of the agent. Kaggriculture is a farming sim where two players
compete to maximize their income from farming by selling to a dynamic market.

Verified against **kaggle-environments 1.32.6**, the version the competition
runs. Check this stamp before trusting a number here: an earlier round of tuning
was measured on 1.32.4, which had different town-demand rules, and every constant
it produced had to be thrown out.

## Overview

Each player starts with an empty farm and a small amount of income (seed money, if you will). Each turn, they can perform actions such as moving around the board, purchasing seeds or livestock, planting seeds, watering plants, harvesting produce or animal products, and selling that produce at the market. The game runs for a fixed amount of time representing one season, and the winner is determined by who has the most money in the bank at the end.

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

For crops, "Yield / tile / day" is total units harvested divided by the days the tile is occupied, watering daily and harvesting at peak yield. For animals it is the steady-state production rate (`1 / interval`) once the first yield lands; animals keep producing for as long as they are fed, so there is no fixed occupancy to divide by. "Max Yield" for animals is `max_held`, the cap on *unharvested* product sitting on the tile, not a lifetime total.

Crop "Time to Max Yield" is the age at which yield stops increasing under daily watering, which is not always the end of the bonus window:

- **Melon**'s bonus window is ages 6–12, but base 1 plus one unit per watered day reaches the cap of 6 at age 10, so ages 11–12 add nothing. Fertilizing reaches the cap at age 8.
- **Wheat** and **Carrot** only reach their listed Max Yield of 6 and 4 with fertilizer; watering alone peaks at 4 and 3.
- **Tomato** and **Strawberry** are ongoing but *not* indefinite: production is capped at 4 scheduled yields (tomato at ages 8–11, strawberry at ages 10, 12, 14, 16), after which the plant decays into a weed.

All plants must be watered every day. They will turn into weeds if they are not watered for two successive days. All animals must be fed every day using wheat. They will escape and be unrecoverable if they are not fed for two successive days. Wheat is also available to buy at the market and can be purchased at the current market price.

## Actions

Each turn, the player may take one action. There are 24 turns per day, and 30 days in the season \- 720 total turns.

### Farmer / Farm Hand Action

Each Farmer / Farm Hand can be given an action every turn. Farmer/Farm Hand CAN occupy the same space.

#### Movement

- NORTH, SOUTH, EAST, WEST — Move one cell in that direction. Moves off the edge of the board are no-ops. Locked tiles are passable: a unit may move onto and across unbought quadrants, but tile actions (`PLANT`, `WATER`, `BUILD_*`, etc.) all no-op on a locked tile and consume nothing.

#### Shed

Picks up an item from the shed (must be orthogonally adjacent) into the inventory

- PICKUP `<item>` `[n]` — move up to `n` of `<item>` (default 1) from the shed into the active farmer/hand's inventory. Any item present in the shed is valid (animals, fertilizer, harvested produce, etc.). Seeds live in a separate slot and are never picked up — `PLANT` consumes them directly.
- DROP — orthogonally adjacent to the shed, dump the active farmer/hand's entire current inventory into the shed. Overflow past `shedCapacity` is discarded. No-op if not shed-adjacent.

#### Plants

- PLANT — Plant a seed purchased from the market  
  - Seeds are automatically available to all Farmers / Farm Hands   
  - If you try to plant too many in a specific turn, none are planted  
    - ie if you have 1 melon seed, but two units do the PLANT MELON command  
- WATER — Water a plant. This only needs to be done once per day, and subsequent waterings on the same day are a no-op.  
- HARVEST — Gather produce from a plant. If the plant does not have subsequent yields, it will be removed from the map. Each harvest action will yield at least one unit of the crop, with the potential of additional yield depending on watering and fertilizer (the formula differs by crop type — see harvest yields below). Harvested items are added to the inventory. 
- FERTILIZE — Fertilize a plant to increase its potential yield (see harvest yields below).  
  - Doubles the per-day yield bonus for the next 3 days. The bonus only applies on days the plant is also watered (basic needs first).

#### Animals

- PLACE `<item>` `[n]` — Drop items from the active farmer/hand inventory into either a tile or the shed:  
  - **Animal placement**: standing on a matching unoccupied structure (`GOOSE` on a coop, `SHEEP`/`COW` on a pasture) places one animal from inventory onto the tile. The `n` argument is ignored.  
  - **Shed drop**: standing orthogonally adjacent to the shed moves up to `n` (default 1) of `<item>` from inventory into the shed. Capped by `shedCapacity`; excess stays in inventory.
- FEED — Feed an animal using wheat (only needs to be done once per day)  
- HARVEST — Collect the eggs/milk/wool produced by the animal.   
- COLLECT\_FERTILIZER — Collect 1 fertilizer from the animal. Every surviving animal makes 1 available at the end of each day, whether or not it was fed or cared for. Uncollected fertilizer does not accumulate, so an animal left alone for five days still yields 1 unit.
- CARE — Care for an animal (once per day, no-op if already cared for). See animal care below.

#### Animal Care

CARE banks a yield bonus that is paid out on the animal's next scheduled production:

* At end of day, if the animal was both fed AND cared for that day, `pending_care_bonus` increments by 1. Days where the animal was unfed do not bank a bonus (basic needs first).
* On a scheduled production day, if the animal is fed, the entire banked bonus is added to that production's yield (in addition to the base 1) and the bank resets to 0.
* If the animal is unfed on the production day, the base 1 unit is still produced, but the banked bonus is not applied and the bank resets to 0.
* `pending_care_bonus` is capped indirectly by the per-animal `max_held` cap on `yield_units`.

#### Terrain

- BUILD\_COOP \- adds a coop to an unoccupied tile  
- BUILD\_PASTURE \- add pasture to an unoccupied tile  
- DIG — Remove a plant from a square to free up space OR remove a weed from a square (does not yield any produce) OR remove an **empty** goose coop / pasture. A coop or pasture with an animal on it cannot be dug; the DIG is a no-op.

#### Other

- PASS — Default if there is nothing to do (optional)

### Market Action

Each turn you can submit up to `maxMarketOrdersPerTurn` (default 10) market actions; any orders past that limit are silently dropped. This is an ordered list and market orders will be processed in order simultaneously (one from each player) while both players have orders.

- BUY\_SEED — Purchase N units of a single item from the market.  
  - BUY\_SEED WHEAT 1  
- BUY\_ANIMAL \-   
  - BUY\_ANIMAL GOOSE 1  
- BUY\_PRODUCT  
  - BUY\_PRODUCT WHEAT 1  
  - BUY\_PRODUCT FERTILIZER 1  
- SELL — Sell N units of a single item to the market.  
  - SELL WHEAT 1  
- HIRE — Hire a farm hand for the day. Cost increases for each extra hand hired on the same day.  
- BUY\_LAND \- unlock a new 5x5 segment of land to plant on. Increasing in cost.   
  - Costs are: $1k, $2k, $4k

## Watering / Animal Feed

Plants (and animals) must be watered/fed a minimum of every other day. Watering only needs to be done once per day, and subsequent watering actions are a no-op. In the case of plants not watered for two consecutive days, at the end of the day they turn into a WEED. In the case of animals they escape (unrecoverable).

A new seed starts with `consecutive_unwatered = 1` — the planting day itself counts as the first missed day. A seed planted and left unwatered that same day reaches 2 at the end-of-day refresh and becomes a weed that night, before it grows. There is no grace period for fresh plantings.

A newly placed animal starts with `consecutive_unfed = 0`, so it survives its first day unfed.

Note that watering one-time yield plants during their yield window results in a higher yield. This is NOT true for ongoing yield plants/animals. See below.

## Harvest Yields

Plants will potentially have higher yields based on how well they have been cared for. 

* **One-time crops** (wheat, carrot, melon): Starting at half the plant's `max_yield_day` (Time to Max Yield) rounded up, watering during the bonus window will add one unit per day to the total harvestable yield.  
  * Fertilized plants add 2 per day instead.  
* **Ongoing crops** (tomato, strawberry): Scheduled production happens at fixed intervals. The base yield is 1 per scheduled production. If the plant is fertilized AND watered that day, yield is doubled to 2.  
* Once a plant has hit its maximum lifespan, the total yield available on the plant will reduce by 1 every other turn until it hits 0, at which point the plant becomes a weed.
  * **One-time crops** reach max lifespan one day after `max_yield_day`.
  * **Ongoing crops** start decay one day after their cumulative production count reaches `max_yield` (i.e. they've fired enough scheduled productions to hit the cap, regardless of whether the produce has been harvested).

## Map Features

Each player has their own farm with a set number of squares. Players are unable to see the state of the other’s shed, but can see the state of their opponent’s farm.

### Farm Space

- The land near your farm is a `boardSize` × `boardSize` grid (default 10×10), divided into four 5×5 quadrants. At first, your farm covers one quadrant (25% of the squares). For an increasingly large fee, you can buy the neighboring quadrants and eventually cover 100% of the squares.  
- Each plant or animal occupies one square on the farm.  
- Players can allocate these squares however they choose between crops and livestock. There are no specific limits per type.  
- Weeds have a chance of spawning on any empty cells on the farm, and must be cleared before the land can be used for other purposes.  
- Squares on the farm can be either a plant, a coop/pasture, a weed, or empty.

### Shed (Inventory)

- Functions as an inventory for items that are harvested but not yet sold, or for seeds that have not yet been planted  
- Farmer and hired farm hands will spawn at the shed at the start of each day  
- Farmer and hired farm hands drop their inventory at the end of the day in the shed (if there is room)  
- Limited to 100 items, excluding seeds. Once the shed is full, any further items added (via `PLACE` mid-day or end-of-day inventory drop) are discarded — there is no overflow holding area, so stockpiling on farmer/hand inventories does not bypass the cap.
- `DROP` / `PICKUP` / `PLACE` resolve **before** the `LOCKED` tile guard, so all four shed-access tiles work from turn 0 even though three of them sit in locked quadrants. (Every other tile op still no-ops on `LOCKED`.)

The shed sits at the center of the board and is not a tile — it never appears in the `tiles` array, whose only values are `None`, `"LOCKED"`, and structure dicts. "Orthogonally adjacent to the shed" means standing on one of the four center tiles, `(half-1, half-1)`, `(half, half-1)`, `(half-1, half)`, `(half, half)` for `half = boardSize // 2`. At the default `boardSize = 10` those are `(4,4)`, `(5,4)`, `(4,5)`, and `(5,5)`, one in each quadrant.

### Farmer/Farm Hand

#### Hiring

- Hiring is a market order (`HIRE`). It costs more every time you want to hire an additional hand each day. At the end of the day all, hands drop inventory at the farm and disappear (need to be re-hired each day)  
- Cost is `farmHandCostMult * fib(n)` where `n` is the number of hires already made today (fib starts 1, 1, 2, 3, 5, 8, 13, ...).  
  - With the default `farmHandCostMult = 1`: 1, 1, 2, 3, 5, 8, 13, 21, etc… (resets at the start of each day)  
- A hired hand appears orthogonally adjacent to the shed in a free space following NWSE. If there are not open spaces, it looks for the one with the least occupants, breaking ties by NWSE preference
- Spawn placement ignores whether the tile is locked. Since the main farmer starts on `(4,4)`, the least-occupied rule sends the first hire of each day to `(5,4)`, which is locked until the NE quadrant is bought. Locked tiles are passable, so a hand spawned on one can move back to unlocked land.

#### Inventory

- When harvesting or picking items up, they are added to inventory.  
- Can drop items in the shed  
- At the end of the day, all items in all inventory will be added to shed inventory (if there is room). Anything that doesn't fit is discarded — overflow is lost.

### Town Buildings

As the season progresses, new shops unlock at regular intervals (every `townShopUnlockInterval` days, default 3). Each unlock is drawn **with replacement** from the full shop list, so the same shop can unlock repeatedly and each copy consumes independently — variety is not guaranteed. Only the total instance count is capped, at `MAX_SHOP_INSTANCES = 8`. Once unlocked, a shop stays active for the rest of the game, so total demand grows monotonically until the cap. (Before 1.32.6 the draw was without replacement, giving 8 distinct shops.)

Each unlocked shop consumes one of every product it demands every `townShopSellInterval` turns (default 4). So with the default interval, a shop demanding wheat removes 6 wheat from the market per day. Single-product shops consume 2x.

In addition, the town center consumes one of every product (excluding fertilizer) every `townCenterSellInterval` turns (default 24 — once a day). Demand is **flat at 1 unit per product per tick all season**; it does not scale with the calendar. Before 1.32.6 the interval was 12 (twice a day) and a demand schedule doubled it after day 10 and quadrupled it after day 20, so late-season town-centre demand was 8 units/day where it is now 1. Any strategy that banks on late-game town demand is tuned to a game that no longer exists.

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

The market has an unlimited supply of seeds and animals at fixed prices. Sell prices, however, move dynamically per resource and persist across days.

Every product (and fertilizer) starts the game with a market inventory of `I0 = 10,000` units, far above any single game's realistic production volume so that inventory is essentially guaranteed to stay positive. The sell price for a product is `base` at `I0`, rises as inventory falls (players buying or town consumption draining supply), and falls as inventory grows (players selling).

### Selling inventory to the market

Players can queue any number of sell or buy orders (for any quantity) in the market action list. Orders are processed concurrently across players, one unit at a time. For example, when both players issue `SELL CARROT 10` first, we take the current carrot price, give both players that price for their first carrot, then add 2 carrots to the market (1 from each player) — which may shift the price — and repeat until both orders complete.

If the sell price has been driven down to `$1` (the price floor), the unit is still purchased but is *not* added to market inventory, so the floor remains responsive to subsequent buys.

### Buying inventory from the market

Only `WHEAT` and `FERTILIZER` can be bought from the market via `BUY_PRODUCT` (other products are sold at the market but not bought back). Selling is unrestricted: every product, including fertilizer collected from animals, can be sold via `SELL`. Two things drain market inventory: town buildings (town center and shops, which consume products for free) and player `BUY_PRODUCT` orders. Buy orders follow the same one-unit-at-a-time concurrent procedure as sell orders. If a player runs out of money mid-order, the order is stopped.

The buy price is quoted at the post-buy inventory and the sell price is quoted at the pre-sell inventory, so an immediate buy followed by a sell of the same item against an otherwise-unchanged market nets exactly zero.

### The Price Function

For each resource the curve is defined by a base price, an anchor throughput `T`, and an independent **shape function** + **target move** for each side of the equilibrium:

```
price(inv) = base + sign · amp · f(|inv − I0|)
  sign = +1  if inv < I0   (scarcity → price up)
  sign = −1  if inv > I0   (glut    → price down)
  amp  = target · base / f(T)        (derived; not stored)
  f    ∈ { linear, sq, sqrt, log, log10 }   (log uses ln(1+x), so f(0)=0)
```

Floored at `$1` and rounded to the nearest dollar.

`T` is the production capacity of a single 5×5 field over a 24-day window at optimal watering with no fertilizer (animal totals are pre-discounted by 30% to account for wheat-feed overhead, and allow one day to build the coop or pasture). The 24-day window is a calibration horizon, not the 30-day season length. It is shorter on purpose: the opening days are setup-heavy and yield little.

`target` says "moving `T` units past `I0` shifts the price by `target × base`." Picking different `f` and `target` on each side lets resources with similar production profiles play very differently strategically — wheat panics on scarcity but absorbs gluts, carrot is the opposite; melon barely reacts to scarcity but crashes hard on overproduction; wool mirrors melon at a smaller scale. Premium resources (base > $100: strawberry, melon, milk, wool) use `above_target > 1`, so even modest gluts drive them straight to the $1 floor — bundling and timing sales matters more for these than for staples.

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

The defaults live in `MARKET_PARAMS` in `kaggriculture.py`. Per-resource overrides (sparse: any subset of `base`, `I0`, `T`, `below_func`, `below_target`, `above_func`, `above_target`) can be supplied at episode creation via `env.configuration["marketParams"]` without touching code, e.g. `{"WOOL": {"above_target": 0.95}}`.

## Turn Processing Order

1. **Action validation** — verify action legality  
2. **Player actions** — record the actions taken by each player (happening simultaneously)  
3. **Market actions** \- process market queue in order by player (described above)  
4. **Town buy actions** \- town center and shops reduce inventory  
5. **Update observations**  
   - **Day refresh** — if applicable, update the condition of plants and animals for a new day, and reset their fed/watered to condition to false  
   - **Market refresh** — modify the price of items on the market based on sells from previous turn  
   - **Income update** — update the player’s bank based on any buys or sells  
   - **Farm update** — clear plants that have been harvested, items from the inventory that have been used or sold, add new plants/animals to the farm, etc

## Win Conditions

The win condition is simple- whoever has the greatest number of coins at the end of the season is the winner. It is also possible that the two players will tie.

## Reward

The player who has the most money in the bank at the end of the game wins. Unsold items in the inventory do not count towards that total.

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
  "private": {             # this player only; opponent's private state is not visible
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
    "consecutive_unwatered": int,   # 2+ → tile turns to a weed
    "yield_units":          int,    # units currently harvestable
    "max_lifespan_step":    int,    # step at which decay begins; -1 for ongoing crops
    "fertilized_until_day": int,    # last day fertilizer bonus applies; -1 if none
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
    "fertilizer_available": bool,   # set at end-of-day for every surviving animal; cleared by COLLECT_FERTILIZER
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

Per-crop seed costs and per-product base prices are not configurable; they are documented in the Object Types and Price Function tables above. The configurable knobs are:

| Parameter | Default | Description |
| :---- | :---- | :---- |
| episodeSteps | 720 | Total turns in the season (24 turns × 30 days) |
| boardSize | 10 | Width and height (in tiles) of each player's square farm. Advanced uses 10 = four 5x5 quadrants |
| startingMoney | 3000 | Coins each player starts with |
| maxMarketOrdersPerTurn | 10 | Maximum number of market orders processed per player per turn; extras are silently dropped |
| turnsPerDay | 24 | Number of turns that make up one in-game day |
| shedCapacity | 100 | Max non-seed items the shed can hold; overflow at end-of-day drop is discarded |
| weedSpawnChance | 0.005 | Per-tile probability of a weed spawning on an empty unlocked tile during end-of-day refresh |
| townShopUnlockInterval | 3 | Days between successive town shop unlocks |
| townShopSellInterval | 4 | Turns between consumption ticks by every unlocked town shop |
| townCenterSellInterval | 24 | Turns between consumption ticks by the town center — once a day. Was 12 (twice a day) before 1.32.6 |
| farmHandCostMult | 1 | Multiplier on the fibonacci hire cost; `n`th hire of the day costs `farmHandCostMult * fib(n)` |
| marketParams | {} | Sparse per-resource overrides of the price-function parameters (see The Price Function) |
| seed | null | Optional input seed for deterministic episode generation; cleared from config after read so it stays out of agent observations |

