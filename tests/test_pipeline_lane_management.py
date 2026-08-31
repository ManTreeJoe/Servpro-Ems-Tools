import trello_client as tc


def test_create_list_posts_board_name_and_position(monkeypatch):
    calls = []
    monkeypatch.setattr(tc, "_call", lambda path, **kwargs: calls.append((path, kwargs)) or {"id": "l1"})
    assert tc.create_list("b1", "  New lane  ")["id"] == "l1"
    assert calls == [("/lists", {"method": "POST", "data": {
        "idBoard": "b1", "name": "New lane", "pos": "bottom"}})]


def test_update_list_only_sends_fields_requested(monkeypatch):
    calls = []
    monkeypatch.setattr(tc, "_call", lambda path, **kwargs: calls.append((path, kwargs)) or {"id": "l1"})
    tc.update_list("l1", name="Ready", pos=123, closed=False)
    assert calls[0] == ("/lists/l1", {"method": "PUT", "params": {
        "name": "Ready", "pos": 123, "closed": "false"}})


def test_lane_controls_are_present_in_pipeline_ui():
    source = open("pipeline_web_assets/app.js", encoding="utf-8").read()
    for marker in ("data-add-lane", "data-lane-menu", "onLaneDragStart",
                   "reorder_lane", "rename_lane", "archive_lane"):
        assert marker in source
