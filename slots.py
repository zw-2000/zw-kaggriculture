"""Are our sells losing market slots to our own hiring?

    .venv/bin/python slots.py /tmp/kagg-replays/episode-*.json

Only ten orders clear per turn and extras are silently dropped. main.py sends
`(sells[:free] + orders + sells[free:])[:10]` with `free = 10 - len(orders)`, so
every one-shot order -- a HIRE above all -- costs a sell slot, and a dropped sell
leaves that stock in the shed for a turn with no trace anywhere.

Reads the submitted `action.market` straight out of a recorded replay, so it
measures what we actually sent in a live season rather than a simulation of it.
A saturated turn (ten orders) is the only turn on which a sell can have been
dropped, so `sat` is the ceiling on the damage and `sell share` says who is
winning the contested slots.
"""
import json
import sys
from collections import Counter

TEAM = "Zhian Wei"


def read(path):
    replay = json.load(open(path))
    names = replay["info"]["TeamNames"]
    out = {}
    for seat in (0, 1):
        turns = sat = sells = others = 0
        verbs = Counter()
        for step in replay["steps"]:
            market = (step[seat].get("action") or {}).get("market")
            if market is None:
                continue
            turns += 1
            sat += len(market) >= 10
            for op in market:
                verbs[op[0]] += 1
                if op[0] == "SELL":
                    sells += 1
                else:
                    others += 1
        out[names[seat]] = dict(turns=turns, sat=sat, sells=sells, others=others,
                                verbs=dict(verbs.most_common(6)))
    return names, out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for path in sys.argv[1:]:
        names, out = read(path)
        print("##", path.rsplit("/", 1)[-1])
        for name, d in out.items():
            tag = "US " if name == TEAM else "OPP"
            total = d["sells"] + d["others"]
            print(f'  {tag} {name[:22]:<22} turns={d["turns"]:>4} '
                  f'saturated={d["sat"]:>4} ({d["sat"] / max(1, d["turns"]):>5.1%})  '
                  f'orders={total:>5} sell_share={d["sells"] / max(1, total):>5.1%}')
            print(f'      {d["verbs"]}')
