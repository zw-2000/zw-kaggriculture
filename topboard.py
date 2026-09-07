"""Print the current public-leaderboard head and our own row.

    .venv/bin/python topboard.py [N]

Refreshes what frontier.py's hardcoded TOP dict cannot: the leaderboard head
moves, so top-agent study must start from a live reading, not an August list.
"""
import sys

from kaggle.api.kaggle_api_extended import KaggleApi

from frontier import call

TEAM_ID = 16667994


def head(n=10):
    api = KaggleApi()
    api.authenticate()
    comp = api.competitions_list(search="kaggriculture").competitions[0]
    board = call("competitions.LeaderboardService", "GetLeaderboard",
                 {"competitionId": comp.id, "leaderboardType": "PUBLIC"})
    rows = board["publicLeaderboard"]
    mine = next(r for r in rows if r["teamId"] == TEAM_ID)
    return rows[:n], mine, len(rows)


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    top, mine, total = head(count)
    for row in top:
        print(f'{row["rank"]}\t{row["teamId"]}\t{row.get("submissionId")}\t'
              f'{row["displayScore"]}\t{row.get("teamName")}')
    print(f'US\t{mine["teamId"]}\t{mine["submissionId"]}\t{mine["displayScore"]}\t'
          f'rank {mine["rank"]} of {total}')
