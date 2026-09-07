"""Run with python3 test_monitor.py; no network or credentials required."""
from monitor import summarize

board = {"publicLeaderboard": [
    {"teamId": 99, "rank": 10, "displayScore": "2800.0", "submissionId": 8},
    {"teamId": 7, "rank": 3000, "displayScore": "997.1", "submissionId": 2},
]}
subs = [{"ref": 1, "publicScore": "1151.7"},
        {"ref": 2, "publicScore": "997.1"},
        {"ref": 3, "publicScore": ""}]
s = summarize(board, subs, [{"id": 2}, {"id": 3}], 7)
assert s["rank"] == 3000 and s["leaderboard_submission"] == 2
assert s["best_historical_submission"] == 1
assert s["active_submissions"] == [2, 3]
assert s["top10_cutoff"] == 2800 and s["score_gap"] == 1802.9
assert not s["top10"]
assert summarize(board, [], [], 99)["top10"]
try:
    summarize(board, subs, [], 404)
except ValueError:
    pass
else:
    raise AssertionError("Missing team must not become a successful snapshot")
print("MONITOR_CHECKS_PASSED")
