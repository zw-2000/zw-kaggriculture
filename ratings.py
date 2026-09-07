"""Rating against episode count, which is the only fair way to compare two of
our own submissions.

    .venv/bin/python ratings.py [n_submissions]

Every submission enters at 600 and climbs as episodes play, so a score read at
seven episodes and a score read at seventy are not comparable numbers -- the
mistake FINDINGS section 18 had to correct. This prints, per submission, the
current public score beside the completed-episode count and the win-loss record
that produced it, and appends the same rows to ratings.tsv so a trajectory
accumulates across sessions.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

from episodes import _episodes

LOG = Path(__file__).with_name("ratings.tsv")
HEADER = "utc\tsubmission\tscore\tepisodes\twins\tlosses\tties\tmean_reward\tdescription\n"


def rows(limit):
    api = KaggleApi()
    api.authenticate()
    subs = [json.loads(str(s)) for s in
            api.competition_submissions("kaggriculture", page_size=100)]
    scored = [s for s in subs if s.get("publicScore") not in (None, "")][:limit]
    out = []
    for sub in scored:
        eps = _episodes(sub["ref"])
        wins = sum(1 for e in eps if e["result"] == "WIN")
        losses = sum(1 for e in eps if e["result"] == "LOSS")
        ties = len(eps) - wins - losses
        mean = sum(e["reward"] for e in eps) / len(eps) if eps else 0.0
        out.append({
            "submission": sub["ref"],
            "score": float(sub["publicScore"]),
            "episodes": len(eps),
            "wins": wins, "losses": losses, "ties": ties,
            "mean_reward": mean,
            "description": (sub.get("description") or "").split(".")[0][:60],
        })
    return out


def main(limit):
    now = datetime.now(timezone.utc).isoformat()
    if not LOG.exists():
        LOG.write_text(HEADER)
    with LOG.open("a") as handle:
        print(f'{"submission":>10} {"score":>8} {"eps":>4} {"W-L-T":>10} {"mean":>9}  what')
        for row in rows(limit):
            print(f'{row["submission"]:>10} {row["score"]:>8.1f} {row["episodes"]:>4} '
                  f'{row["wins"]}-{row["losses"]}-{row["ties"]:<6} '
                  f'{row["mean_reward"]:>9,.0f}  {row["description"]}')
            handle.write(f'{now}\t{row["submission"]}\t{row["score"]}\t{row["episodes"]}\t'
                         f'{row["wins"]}\t{row["losses"]}\t{row["ties"]}\t'
                         f'{row["mean_reward"]:.0f}\t{row["description"]}\n')


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
