"""Commercial-parent sub-job 'misfiled' fallback (audit_logic).

A campus sub-job (e.g. "Menifee Union School District \\ Kirkpatrick
Elementary") is audited against its OWN folder first; anything missing
there but present elsewhere in the parent tree is MISPLACED (wrong
folder), not missing. Locks `forms_found_in_tree` +
`photos_found_in_siblings`.
"""
import audit_logic as al


# ── forms_found_in_tree ──────────────────────────────────────────────
def test_forms_found_when_filed_under_sibling_campus(tmp_path):
    parent = tmp_path / "Menifee Union School District"
    campus_a = parent / "Kirkpatrick Elementary"
    campus_b = parent / "Callahan Elementary"
    (campus_a / "EMS").mkdir(parents=True)
    (campus_b / "EMS").mkdir(parents=True)
    # ATP filed under the WRONG campus (B), missing from A.
    (campus_b / "EMS" / "ATP signed.pdf").write_text("x", encoding="utf-8")

    found = al.forms_found_in_tree(
        str(parent), ["Auth to Perform"], skip_dir=str(campus_a))
    assert "Auth to Perform" in found
    assert "Callahan Elementary" in found["Auth to Perform"]


def test_forms_in_own_folder_are_not_misplaced(tmp_path):
    # A form present ONLY in the campus's own folder (skip_dir) must not
    # count as "found elsewhere" — it's correctly filed.
    parent = tmp_path / "Parent"
    campus_a = parent / "A"
    (campus_a / "EMS").mkdir(parents=True)
    (campus_a / "EMS" / "ATP.pdf").write_text("x", encoding="utf-8")

    found = al.forms_found_in_tree(
        str(parent), ["Auth to Perform"], skip_dir=str(campus_a))
    assert found == {}


def test_forms_truly_absent_returns_empty(tmp_path):
    parent = tmp_path / "Parent"
    (parent / "A" / "EMS").mkdir(parents=True)
    assert al.forms_found_in_tree(str(parent), ["Auth to Perform"]) == {}


# ── photos_found_in_siblings ─────────────────────────────────────────
def test_photos_found_when_initial_under_sibling(tmp_path):
    parent = tmp_path / "Parent"
    campus_a = parent / "A"
    campus_b = parent / "B"
    (campus_a / "EMS" / "PICS").mkdir(parents=True)
    initial_b = campus_b / "EMS" / "PICS" / "Initial"
    initial_b.mkdir(parents=True)
    (initial_b / "img1.jpg").write_text("x", encoding="utf-8")

    found = al.photos_found_in_siblings(
        str(parent), str(campus_a), ["Initial pics"])
    assert "Initial pics" in found
    assert "B" in found["Initial pics"]


def test_photos_absent_everywhere_returns_empty(tmp_path):
    parent = tmp_path / "Parent"
    (parent / "A" / "EMS" / "PICS").mkdir(parents=True)
    (parent / "B" / "EMS" / "PICS").mkdir(parents=True)
    assert al.photos_found_in_siblings(
        str(parent), str(parent / "A"), ["Initial pics"]) == {}
