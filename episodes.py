"""List and download live episodes for any submission.

    .venv/bin/python episodes.py list <submissionId> [limit]
    .venv/bin/python episodes.py get <episodeId> [destdir]
    .venv/bin/python episodes.py losses <submissionId> [limit] [destdir]

`list` prints one completed head-to-head episode per line as
`episodeId  ourReward  oppReward  oppTeamId  result`, newest first, so a losing
game can be picked without opening a 25MB replay. `losses` downloads the newest
losses, which is the only sample that can teach anything the mirror cannot.

Replays land as <destdir>/episode-<id>-replay.json, the layout replay_check.py
and decision_check.py already expect.
"""
import os
import sys

from frontier import call

# Neither the /api/i EpisodeService route nor kaggle_environments.api's public
# /requests route serves replays any more (404 and 400 respectively). The
# authenticated SDK method is the one that still works.


def _episodes(submission):
    data = call("competitions.EpisodeService", "ListEpisodes",
                {"submissionId": int(submission)})
    rows = []
    for ep in data.get("episodes", []):
        agents = ep.get("agents", [])
        mine = next((a for a in agents if a.get("submissionId") == int(submission)), None)
        if not mine or ep.get("state") != "COMPLETED" or len(agents) != 2:
            continue
        opp = next(a for a in agents if a is not mine)
        if mine.get("reward") is None or opp.get("reward") is None:
            continue
        rows.append({
            "episode": ep["id"],
            "seat": mine.get("index"),
            "reward": mine["reward"],
            "opponent_reward": opp["reward"],
            "opponent_team": opp.get("teamId"),
            "result": "WIN" if mine["reward"] > opp["reward"] else
                      "LOSS" if mine["reward"] < opp["reward"] else "TIE",
        })
    rows.sort(key=lambda r: r["episode"], reverse=True)
    return rows


def download(episode, destdir="/tmp/kagg-replays"):
    os.makedirs(destdir, exist_ok=True)
    dest = os.path.join(destdir, f"episode-{episode}-replay.json")
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return dest
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    api.competition_episode_replay(int(episode), path=destdir)
    if not os.path.exists(dest):
        raise SystemExit(f"replay download produced no {dest}")
    return dest


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    command, target = argv[1], argv[2]
    if command == "list":
        limit = int(argv[3]) if len(argv) > 3 else 40
        for row in _episodes(target)[:limit]:
            print(f'{row["episode"]}\t{row["reward"]:.0f}\t{row["opponent_reward"]:.0f}\t'
                  f'{row["opponent_team"]}\tseat{row["seat"]}\t{row["result"]}')
    elif command == "get":
        print(download(target, argv[3] if len(argv) > 3 else "/tmp/kagg-replays"))
    elif command == "losses":
        limit = int(argv[3]) if len(argv) > 3 else 3
        destdir = argv[4] if len(argv) > 4 else "/tmp/kagg-replays"
        picked = [r for r in _episodes(target) if r["result"] == "LOSS"][:limit]
        for row in picked:
            print(download(row["episode"], destdir), row["reward"], row["opponent_reward"])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
