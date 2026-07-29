"""Misfiled tag must NOT fire spuriously (bug 2026-06-22 — "flags everything").

Two false-positive sources fixed:
  1. photos_found_in_siblings included the bare PARENT CONTAINER as a
     candidate. The container has no DOCS, so check_docusketch returns []
     ("nothing to check"), which the "satisfied = not missing" test read as
     "docusketch found here" → every unit flagged misfiled at where='.'.
  2. The cross-sibling scan ran for multi-unit apartments, where each unit
     independently owns its paperwork — a sibling unit having its own
     Scope/docusketch is normal, not a misfile.
"""
import audit_logic as al


def test_parent_container_not_a_candidate(tmp_path):
    # Parent container with NO DOCS of its own + a unit that is missing its
    # docusketch. The container must NOT be reported as where the docusketch
    # "is" (the old where='.' false positive).
    parent = tmp_path / "Avila Apartments 2026"
    unit_a = parent / "Unit 1017"
    unit_b = parent / "Unit 1413"
    (unit_a / "EMS" / "DOCS").mkdir(parents=True)   # has DOCS, no docusketch
    (unit_b / "EMS" / "DOCS").mkdir(parents=True)
    found = al.photos_found_in_siblings(
        str(parent), str(unit_a), ["Docusketch folder missing from DOCS"])
    # Neither unit has a real docusketch → nothing is "found elsewhere".
    assert found == {}
    assert "." not in found.values()


def test_docusketch_not_credited_to_folder_without_docs(tmp_path):
    # A sibling with EMS but NO DOCS folder must not be credited as holding
    # a docusketch (check_docusketch returns [] there for lack of DOCS).
    parent = tmp_path / "Parent"
    a = parent / "A"
    b = parent / "B"
    (a / "EMS").mkdir(parents=True)          # campus A, no DOCS
    (b / "EMS").mkdir(parents=True)          # campus B, no DOCS
    found = al.photos_found_in_siblings(
        str(parent), str(a), ["Docusketch has no .esx file"])
    assert found == {}


def test_real_docusketch_in_sibling_still_found(tmp_path):
    # Positive case preserved: sibling B has a valid docusketch (.esx).
    parent = tmp_path / "District"
    a = parent / "Campus A"
    b = parent / "Campus B"
    (a / "EMS" / "DOCS").mkdir(parents=True)
    sketch = b / "EMS" / "DOCS" / "Docusketch"
    sketch.mkdir(parents=True)
    (sketch / "tour.esx").write_text("x", encoding="utf-8")
    found = al.photos_found_in_siblings(
        str(parent), str(a), ["Docusketch folder missing from DOCS"])
    assert "Docusketch folder missing from DOCS" in found
    assert "Campus B" in found["Docusketch folder missing from DOCS"]
