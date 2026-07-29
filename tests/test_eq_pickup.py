"""EQ pickup is a standalone snapshot log activity.

"Pick up EQ - FB" (and variants) should each produce their own dated log
row so the snapshot shows the equipment retrieval."""
from snapshot_logic import parse_comments


def _logs(raw):
    return parse_comments(raw)[1]


def test_pick_up_eq_dispatch_line():
    raw = "Tuesday 6/30/26\n\nPick up EQ - FB\n"
    logs = _logs(raw)
    assert logs == [("6/30/26", "Tuesday", "EQ Pickup", "FB")]


def test_air_scrubber_picked_up():
    logs = _logs("6/20/26 Air scrubber picked up - ME")
    assert logs and logs[0][2] == "EQ Pickup" and logs[0][0] == "6/20/26"


def test_eq_picked_up_order_variants():
    for line in ("6/1/26 EQ pickup", "6/1/26 Equipment picked up",
                 "6/1/26 Pick up equipment"):
        logs = _logs(line)
        assert logs and logs[0][2] == "EQ Pickup", line


def test_unrelated_line_not_eq_pickup():
    logs = _logs("6/1/26 Demo - FB")
    assert all(a != "EQ Pickup" for _d, _w, a, _t in logs)
