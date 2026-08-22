# Kaggriculture JAX Engine — Phase 1 of the Self-Play RL Rebuild

## Context

The current Kaggriculture agent (`main.py`/`baseline.py`) is a hand-tuned
heuristic, iterated via `bench.py` (seeded self-play benchmarking) and
`frontier.py` (analysis of top-leaderboard replays). The goal explored here
is a full self-play RL rebuild in the spirit of AlphaZero, targeting the
active Kaggle "kaggriculture" competition with a hard deadline in
**~1 month** (from 2026-08-23) and a local RTX 3060 Ti GPU available.

Verification before this design (see conversation) established two
structural mismatches with vanilla AlphaZero that any rebuild must account
for:

- **Imperfect information** — each player's `private.shed`, `private.seeds`,
  and `private.inventories` are hidden from the opponent, so vanilla MCTS
  (which assumes a fully observable state to search from) doesn't apply
  as-is. The venv already has `open_spiel` installed, which ships
  ISMCTS/PIMC/CFR-family implementations for exactly this class of problem —
  planned for the phase-2 (algorithm) spec, out of scope here.
- **Combinatorial per-turn action space** — one turn is `farmer op × per-hand
  ops × up to 10 ordered market orders`, not a single discrete move. Also
  deferred to phase 2 (action/state representation for search).

The user chose to accept the risk of the full rebuild over a smaller
descoped version (a value-net-augmented lookahead on the existing engine),
understanding that within a 1-month window there is a real chance nothing
beats the current heuristic in time. The existing heuristic stays the actual
Kaggle submission throughout, gated by `bench.py`, until/unless a trained
agent beats it there.

This spec covers **only phase 1**: a fast, faithful, JAX-vectorized
reimplementation of the Kaggriculture rules engine, needed because the real
`kaggle_environments` simulator is pure Python and too slow to generate
self-play volume for training. Phases 2 (imperfect-info search/training
algorithm) and 3 (integration into `main.py`, gated by `bench.py`) are
separate specs, written once this one is real and tested.

## Goal

A JAX-native Kaggriculture engine that:
1. Reproduces the full rule set at
   `.venv/lib/python3.12/site-packages/kaggle_environments/envs/kaggriculture/README.md`
   with no simplifications (a policy trained against a simplified engine
   won't transfer to the real, Kaggle-scored one).
2. Is `vmap`-able over a batch of parallel games for GPU-scale self-play
   throughput.
3. Is validated against the real `kaggle_environments` engine via
   incremental differential testing, not a single end-of-project check.

## Non-Goals

- No search algorithm, policy, or value network (phase 2).
- No changes to `main.py`, `baseline.py`, `bench.py`, or `frontier.py` — the
  existing heuristic and its measurement harness are the ground truth for
  "does this actually win" throughout, and are untouched by this phase.
- No attempt to bit-reproduce the real engine's Python `random` draws (see
  Validation Strategy) — statistical equivalence is the bar for the
  stochastic pieces, not identical RNG streams.

## State Representation

Fixed-shape arrays, one struct per tile with a `kind` enum and every
possible field present (unused fields zeroed/masked) — the standard
technique for representing heterogeneous state (`None` / `"LOCKED"` /
plant-dict / weed-dict / structure-dict in the real engine) in a vectorized
JAX environment.

| Dimension | Shape | Note |
|---|---|---|
| Board | `(10, 10)` per player | Matches the real default `boardSize` |
| Market orders/turn | 10 | Matches real `maxMarketOrdersPerTurn` |
| Hired hand slots | **16** (assumption) | The real game has no hard cap, but Fibonacci hire cost (`1,1,2,3,5,8,13,21,...`) against `startingMoney=3000` makes hiring past ~12–15 in one day economically absurd long before it's reachable. A policy that tries to hire a 17th hand should surface as a bug signal, not silently truncate — implement the cap as an assertion/loud failure, not a silent clamp. |

Every crop type (Wheat, Carrot, Tomato, Strawberry, Melon), every animal
type (Goose, Cow, Sheep), fertilizer, market price curves (per-resource
`base`/`I0`/`T`/shape-function pairs from `MARKET_PARAMS`), town shops, and
the town center are all in scope — see the Object Types, Market Mechanics,
and Town Buildings tables in the real engine's README for the exact rules
to port.

## Validation Strategy

The risk with a from-scratch rules port is silent divergence from the real
engine in some edge case, not "does it run." Two validation modes, because
RNG streams between the real engine's Python `random` and JAX's splittable
`PRNGKey` can never be bit-identical and forcing them to would be wasted
effort:

1. **Deterministic rule logic** (yields, watering/feeding decay, market
   price curve, hire costs, land unlocking, shed capacity/overflow): test
   with randomness disabled (`weedSpawnChance=0`, no shop unlocks), replay
   the same action sequence through both engines, assert **step-by-step
   observation equality** across a full 720-turn episode.
2. **The stochastic pieces themselves** (weed spawn rate, shop-unlock
   draws): validated statistically across many episodes — empirical
   rate/distribution matches the configured parameter within tolerance, not
   an exact-draw comparison.

A new differential-test harness takes action trajectories from the existing
agents (`main.py`'s agent, `"random"`, `"starter"`) across `bench.py`'s
existing 60-seed list, runs them through both engines in lockstep, and fails
loud on the first diverging field. This harness is built alongside the
engine from day one and doubles as the regression suite for the whole
rewrite — **each rule is diff-tested immediately after being ported**, never
validated only at the end.

## Build Order & Milestones (~1.5 weeks)

Each step diff-tested (per above) before moving to the next:

1. Core loop skeleton — board, movement, shed pickup/drop/place, `PASS`. No
   crops/animals/market yet.
2. Wheat only (simplest one-time crop) + `BUY_SEED`/`SELL` with the real
   price function — the template the other crops parametrize off of.
3. Remaining crops (Carrot, Tomato, Strawberry, Melon).
4. Animals (Goose, Cow, Sheep) — the most stateful subsystem
   (`consecutive_unfed`, `pending_care_bonus`).
5. Land unlocking, hiring, shed capacity/overflow.
6. Town shops + town center consumption (the stochastic-unlock piece).
7. **Acceptance gate**: full-episode diff test across `bench.py`'s 60 seeds
   — deterministic-mode step equality + stochastic-mode distribution match —
   before phase 2 begins.

## Interface Boundary (for phase 2)

The engine exposes a `step(state, actions) -> state, obs` function over the
fixed-shape state above, `vmap`-able over a batch dimension for parallel
self-play games. It does not decide actions, run search, or expose a
policy — phase 2 (the imperfect-info search/training algorithm) is a
separate spec, written once this engine passes its acceptance gate.

## How This Fits the Existing Measurement Discipline

`bench.py` and `frontier.py` are untouched and remain the actual ground
truth: they measure the real `kaggle_environments` engine, which is what the
Kaggle leaderboard runs. This JAX engine only accelerates training — it
never gets to claim a win on its own. A trained agent only counts once it's
wired into `main.py` and beats the current heuristic in `bench.py`, exactly
like every prior change in this repo's history (see git log). The rewrite
adds to that discipline; it does not replace it.

## Risks

- **Timeline**: 1 month total must cover phases 1–3. If phase 1 overruns
  its ~1.5-week budget, phases 2/3 lose runway and the fallback is
  submitting the existing heuristic, unchanged, as scoped in the earlier
  risk-appetite discussion.
- **Silent rule divergence**: mitigated by incremental diff-testing (see
  above), not eliminated by it — a subtle bug that both engines agree on
  (e.g. a shared misreading of the README) would not be caught by this
  strategy.
- **Hand-slot cap (16)**: an assumption, not a verified constant from the
  real engine. Implemented as a loud failure if exceeded, so it surfaces
  rather than silently corrupting state.
