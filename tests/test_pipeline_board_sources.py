"""Pipeline board-source coverage."""

import pipeline_web


def test_pipeline_includes_all_division_boards():
    assert pipeline_web.BOARD_SPECS == (
        ("wip", "WORK IN PROGRESS"),
        ("est", "ESTIMATING"),
        ("contents", "CONTENTS"),
        ("recon", "RECON WORK IN PROGRESS"),
    )
    assert pipeline_web.BOARD_SHORTLINKS["recon"] == "AmUodHrh"


def test_recon_board_resolves_by_stable_link_even_after_a_rename():
    renamed = {"id": "r1", "name": "RECON PRODUCTION",
               "shortLink": "AmUodHrh"}
    assert pipeline_web._resolve_board(
        [renamed], "RECON WORK IN PROGRESS", "AmUodHrh") is renamed


def test_pipeline_board_keys_are_unique():
    keys = [key for key, _name in pipeline_web.BOARD_SPECS]
    assert len(keys) == len(set(keys))


def test_all_open_lanes_survive_both_read_paths(monkeypatch):
    from types import SimpleNamespace
    import trello_mirror_reader
    names = ('WORK IN PROGRESS', 'TBS NEW LOSS/RE-INSPECTION',
                 'TBS MITIGATION', 'TBS CONTENTS', 'TEST/CLEARANCE',
                 'PENDING APPROVALS/INSURANCE/SELF PAY',
                 'PENDING APPROVALS/PROPERTY MANAGEMENT/COMMERCIAL',
                 'ON HOLD', 'MARKETING TEAM', 'MARKETING - ON HOLD',
                 'SNAPSHOT', 'AMAYA', 'READY FOR REVIEW', 'SPACER',
                 'PROPERTY MANAGEMENT TEMPLATES', 'ON CALL TEAMS',
                 'DISPOSAL', 'GARMENTS', 'LABELS', 'COLLECTIONS PROCESS')
    lists = [dict(id=str(i), name=name, pos=i) for i, name in enumerate(names)]
    board = {'id':'b1', 'name':'WORK IN PROGRESS'}
    tc = SimpleNamespace(_call=lambda path, **kwargs: lists if path.endswith('/lists') else [])
    direct = pipeline_web._build_board(tc, None, 'wip', board['name'], board)
    assert [lane['name'] for lane in direct['lanes']] == list(names)
    monkeypatch.setattr(trello_mirror_reader, 'boards', lambda: [dict(
        board=board, lists=lists + [dict(id='closed', name='Archived', closed=True)],
        cards=[], saved_at='2026-10-07T18:00:00Z')])
    mirrored = pipeline_web._server_board_payload([('wip', board['name'])])
    assert [lane['name'] for lane in mirrored['boards'][0]['lanes']] == list(names)
