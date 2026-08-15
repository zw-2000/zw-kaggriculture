"""Run the agent and see what it did.

    .venv/bin/python play.py                  # vs starter, day-by-day table
    .venv/bin/python play.py random           # pick an opponent
    .venv/bin/python play.py starter 7        # ...and a seed (repeatable episode)
    .venv/bin/python play.py starter 7 watch  # also write replay.html to open

Opponents: starter, random, pass, or a path to another .py agent.
"""
import sys

from kaggle_environments import make

import main

opponent = sys.argv[1] if len(sys.argv) > 1 else "starter"
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
watch = "watch" in sys.argv[3:]

cfg = {"seed": seed}
env = make("kaggriculture", configuration=cfg, debug=True)
env.run([main.agent, opponent])

print(f"me vs {opponent}   seed={seed}\n")
print(f"{'day':>3} {'money':>9} {'geese':>6} {'coops':>6} {'plants':>7} "
      f"{'empty':>6} {'weeds':>6} {'shed':>5}")
for i, step in enumerate(env.steps):
    if i % 24 != 23:                       # last turn of each day
        continue
    o = step[0]["observation"]
    me, priv = o["farms"][0], o["private"]
    tiles = [t for row in me["tiles"] for t in row]
    dicts = [t for t in tiles if isinstance(t, dict)]
    print(f"{i // 24:>3} {me['money']:>9,.0f} "
          f"{sum(1 for t in dicts if t.get('animal')):>6} "
          f"{sum(1 for t in dicts if t.get('kind') == 'COOP' and not t.get('animal')):>6} "
          f"{sum(1 for t in dicts if t.get('kind') == 'PLANT'):>7} "
          f"{sum(1 for t in tiles if t is None):>6} "
          f"{sum(1 for t in dicts if t.get('kind') == 'WEED'):>6} "
          f"{sum(priv['shed'].values()):>5}")

mine, theirs = (s["reward"] for s in env.steps[-1])
print(f"\nFINAL  me={mine:,.0f}  {opponent}={theirs:,.0f}  "
      f"-> {'WIN' if mine > theirs else 'TIE' if mine == theirs else 'LOSS'}")
print("closing prices:", env.steps[-1][0]["observation"]["market"]["prices"])

if watch:
    with open("replay.html", "w") as f:
        f.write(env.render(mode="html", width=1000, height=700))
    print("\nwrote replay.html -- open it in a browser to watch the season")
