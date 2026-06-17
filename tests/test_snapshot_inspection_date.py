"""Tracked-snapshot 'Inspection' column = first-visit / initial-
inspection date. Locks the _row_to_cells wiring: caller-provided
`_first_visit` fills it, an existing manual cell wins.
"""
import snapshots_excel as sx


def test_inspection_filled_from_first_visit():
    cells = sx._row_to_cells({"client": "Jane Doe", "_first_visit": "6/4/26"})
    assert cells["Inspection"] == "6/4/26"


def test_existing_inspection_cell_wins():
    cells = sx._row_to_cells(
        {"client": "Jane Doe", "_first_visit": "6/4/26"},
        existing={"Inspection": "6/1/26"})
    assert cells["Inspection"] == "6/1/26"


def test_inspection_blank_when_no_first_visit():
    cells = sx._row_to_cells({"client": "Jane Doe"})
    assert cells["Inspection"] == ""
