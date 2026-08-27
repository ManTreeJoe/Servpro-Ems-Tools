"""Pipeline board-source coverage."""

import pipeline_web


def test_pipeline_includes_operating_and_contents_boards():
    assert pipeline_web.BOARD_SPECS == (
        ("wip", "WORK IN PROGRESS"),
        ("est", "ESTIMATING"),
        ("contents", "CONTENTS"),
    )


def test_pipeline_board_keys_are_unique():
    keys = [key for key, _name in pipeline_web.BOARD_SPECS]
    assert len(keys) == len(set(keys))
