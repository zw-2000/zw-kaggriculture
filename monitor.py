"""Live standings: .venv/bin/python monitor.py [--interval 900].

Append snapshots to live_monitor.jsonl. Active submissions come from Kaggle's
team endpoint; an older personal best is not necessarily still playing.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time


def summarize(board, submissions, active, team_id):
    rows = board["publicLeaderboard"]
    me = next((r for r in rows if r["teamId"] == team_id), None)
    if me is None:
        raise ValueError(f"Team {team_id} missing from leaderboard")
    cutoff = next(float(r["displayScore"]) for r in rows if r["rank"] == 10)
    scored = [s for s in submissions if s.get("publicScore") not in (None, "")]
    best = max(scored, key=lambda s: float(s["publicScore"]), default=None)
    score = float(me["displayScore"])
    return {
        "rank": me["rank"], "score": score,
        "leaderboard_submission": me["submissionId"],
        "active_submissions": [s["id"] for s in active],
        "best_historical_submission": best["ref"] if best else None,
        "best_historical_score": float(best["publicScore"]) if best else None,
        "top10_cutoff": cutoff, "score_gap": round(cutoff - score, 1),
        "top10": me["rank"] <= 10,
        "submissions": submissions,
    }


def snapshot():
    from kaggle.api.kaggle_api_extended import KaggleApi
    from frontier import call

    api = KaggleApi()
    api.authenticate()
    competition = api.competitions_list(search="kaggriculture").competitions[0]
    board = call("competitions.LeaderboardService", "GetLeaderboard",
                 {"competitionId": competition.id, "leaderboardType": "PUBLIC"})
    team_id = 16667994
    submissions = [json.loads(str(s)) for s in
                   api.competition_submissions("kaggriculture", page_size=100)]
    active = [json.loads(str(s)) for s in api.competition_team_submissions(team_id)]
    result = summarize(board, submissions, active, team_id)
    result.update(utc=datetime.now(timezone.utc).isoformat(),
                  deadline=competition.deadline.replace(tzinfo=timezone.utc).isoformat())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0,
                        help="seconds between checks; zero performs one check")
    args = parser.parse_args()
    if args.interval < 0:
        parser.error("interval must be nonnegative")
    log = Path(__file__).with_name("live_monitor.jsonl")
    while True:
        try:
            result = snapshot()
            with log.open("a") as output:
                output.write(json.dumps(result) + "\n")
            print(json.dumps({k: v for k, v in result.items() if k != "submissions"}),
                  flush=True)
            deadline = datetime.fromisoformat(result["deadline"])
            if datetime.now(timezone.utc) >= deadline:
                break
        except Exception as error:
            print(f"MONITOR_FAILED {datetime.now(timezone.utc).isoformat()} "
                  f"{type(error).__name__}: {error}", file=sys.stderr, flush=True)
            if not args.interval:
                raise SystemExit(1)
        if not args.interval:
            break
        time.sleep(args.interval)
