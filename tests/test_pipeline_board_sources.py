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
