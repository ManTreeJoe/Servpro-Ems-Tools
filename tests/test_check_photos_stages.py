"""Stage-aware photo subfolder checks in audit_logic.check_photos.

The Run Audit needs to flag missing stage photos based on the run-doc
line for the job — Demo, Mold Prep / Post Mold Prep, generic Mold,
Abatement, etc. These tests pin the per-stage expectations against a
real on-disk PICS layout so the run-audit panel can't silently drop a
check when the activity blob mentions a stage.

Each test builds a PICS folder, optionally pre-fills some subfolders
with a placeholder file (so cat_filled returns True), then calls
check_photos with the relevant raw_text. Empty subfolders count as
missing; that mirrors the live behavior (a folder with no photos is
just as bad as no folder at all)."""
import os

from audit_logic import check_photos


def _make_pics(tmp_path, *, filled=(), empty=()):
    """Create a PICS dir with some filled subfolders and some empty."""
    pics = tmp_path / "PICS"
    pics.mkdir()
    for name in filled:
        d = pics / name
        d.mkdir()
        (d / "img.jpg").write_bytes(b"x")
    for name in empty:
        (pics / name).mkdir()
    return str(pics)


def test_no_activity_only_initial_check_fires(tmp_path):
    """Without raw_text or log_rows, only Initial is checked."""
    pics = _make_pics(tmp_path)  # no Initial folder at all
    missing = check_photos(pics)
    assert missing == ["Initial pics"]


def test_missing_pics_folder_flags_initial(tmp_path):
    """When the PICS folder doesn't exist at all, Initial pics must be
    flagged — silently passing was the bug the user saw where the audit
    looked clean for jobs whose folders weren't scaffolded yet."""
    nope = str(tmp_path / "does_not_exist")
    assert check_photos(nope) == ["Initial pics"]


# ── FOH (front of house/structure) + EQ (equipment) sub-folder checks ──
# These live INSIDE the Initial folder: PICS\Initial\FOH and PICS\Initial\EQ.
# FOH is required on the initial visit; EQ once a Monitor visit happens.
def _initial_with(tmp_path, *, subs_filled=(), subs_empty=()):
    """PICS with a filled Initial folder + optional FOH/EQ subfolders."""
    pics = tmp_path / "PICS"
    init = pics / "Initial"
    init.mkdir(parents=True)
    (init / "img.jpg").write_bytes(b"x")
    for name in subs_filled:
        d = init / name
        d.mkdir()
        (d / "p.jpg").write_bytes(b"x")
    for name in subs_empty:
        (init / name).mkdir()
    return str(pics)


def test_foh_flagged_on_initial_when_missing(tmp_path):
    pics = _initial_with(tmp_path)  # Initial filled, no FOH subfolder
    assert "FOH pics" in check_photos(pics, raw_text="Initial Inspection")


def test_foh_satisfied_by_any_name(tmp_path):
    for name in ("FOH", "Front of House", "Front of Structure", "FOS"):
        pics = _initial_with(tmp_path / name, subs_filled=[name])
        assert "FOH pics" not in check_photos(
            pics, raw_text="Initial Inspection"), name


def test_eq_flagged_on_monitor_when_missing(tmp_path):
    pics = _initial_with(tmp_path)  # Initial exists, no EQ
    missing = check_photos(pics, raw_text="Monitor")
    assert "EQ pics" in missing


def test_eq_satisfied_by_folder(tmp_path):
    pics = _initial_with(tmp_path, subs_filled=["EQ"])
    assert "EQ pics" not in check_photos(pics, raw_text="Monitor")


def test_no_foh_eq_nag_on_demo_day(tmp_path):
    """Demo day is neither an initial nor a monitor visit — no FOH/EQ nag."""
    pics = _initial_with(tmp_path)
    (tmp_path / "PICS" / "Demo").mkdir()
    (tmp_path / "PICS" / "Demo" / "d.jpg").write_bytes(b"x")
    missing = check_photos(pics, raw_text="Demo")
    assert "FOH pics" not in missing and "EQ pics" not in missing


def test_foh_nested_under_tech_box(tmp_path):
    """FOH nested under a '<Tech> <date>' box counts — real layout is
    PICS\\Initial\\FB 07-01-2026\\Front of Structure."""
    pics = tmp_path / "PICS"
    init = pics / "Initial"
    box = init / "FB 07-01-2026" / "Front of Structure"
    box.mkdir(parents=True)
    (box / "p.jpg").write_bytes(b"x")
    (init / "a.jpg").write_bytes(b"x")
    assert "FOH pics" not in check_photos(str(pics), raw_text="Initial Inspection")


def test_foh_satisfied_by_companycam_filename(tmp_path):
    """The FOH shot usually arrives as a FILE, not a folder.

    CompanyCam bakes its tags into the exported filename, so the
    front-of-structure photo lands as
    "Front of Structure Initial Inspection-1-Jul 18 2026 12_13pm-jNya.jpg"
    inside the tech/date box. Detection walked for matching FOLDERS at any
    depth but checked FILES only at the top level, so a job that plainly
    had the photo still reported "FOH pics" missing.
    """
    pics = tmp_path / "PICS"
    box = pics / "Initial" / "FB 07-18-2026"
    box.mkdir(parents=True)
    (box / "Front of Structure Initial Inspection-1-Jul 18 2026 "
           "12_13pm-jNya.jpg").write_bytes(b"x")
    (pics / "Initial" / "a.jpg").write_bytes(b"x")
    assert "FOH pics" not in check_photos(
        str(pics), raw_text="Initial Inspection")


def test_foh_filename_match_requires_an_image(tmp_path):
    """A document named for the item is not the photo.

    Widening the file check to any depth would otherwise let
    "Front of Structure notes.docx" satisfy a PHOTO requirement.
    """
    pics = tmp_path / "PICS"
    box = pics / "Initial" / "FB 07-18-2026"
    box.mkdir(parents=True)
    (box / "Front of Structure notes.docx").write_bytes(b"x")
    (pics / "Initial" / "a.jpg").write_bytes(b"x")
    assert "FOH pics" in check_photos(str(pics), raw_text="Initial Inspection")


def test_eq_nested_under_tech_box(tmp_path):
    pics = tmp_path / "PICS"
    init = pics / "Initial"
    box = init / "FB 07-01-2026" / "EQ"
    box.mkdir(parents=True)
    (box / "p.jpg").write_bytes(b"x")
    (init / "a.jpg").write_bytes(b"x")
    assert "EQ pics" not in check_photos(str(pics), raw_text="Monitor")


def test_foh_still_flagged_when_truly_absent(tmp_path):
    """A nested tech box with NO FOH still flags."""
    pics = tmp_path / "PICS"
    box = pics / "Initial" / "FB 07-01-2026" / "Demo Photos"
    box.mkdir(parents=True)
    (box / "p.jpg").write_bytes(b"x")
    (pics / "Initial" / "a.jpg").write_bytes(b"x")
    assert "FOH pics" in check_photos(str(pics), raw_text="Initial Inspection")


def test_missing_pics_folder_with_demo_activity_flags_both(tmp_path):
    """Stage detection still fires when the folder is missing — Demo +
    Initial both end up on the row."""
    nope = str(tmp_path / "does_not_exist")
    missing = check_photos(nope, raw_text="Cesar (Demo) initial visit")
    assert "Initial pics" in missing
    assert "Demo pics" in missing


def test_demo_in_raw_text_flags_demo_pics(tmp_path):
    pics = _make_pics(tmp_path, filled=("Initial",))
    missing = check_photos(pics, raw_text="Joe: 1 St (Demo) Cesar")
    assert "Demo pics" in missing
    # Demo on its own should NOT also imply Post pics — on the day demo
    # happens, post-demo pics don't exist yet (they come on the next
    # visit). Post pics fire only when 'post' is explicitly in the
    # activity. Was a false-positive that flagged every demo job.
    assert "Post pics" not in missing


def test_demo_satisfied_when_demo_folder_has_files(tmp_path):
    pics = _make_pics(tmp_path, filled=("Initial", "Demo", "Post"))
    missing = check_photos(pics, raw_text="Joe: 1 St (Demo) Cesar")
    assert "Demo pics" not in missing
    assert "Post pics" not in missing


def test_explicit_post_in_activity_flags_post_pics(tmp_path):
    """When the run-doc explicitly says 'Post' (e.g. 'Post Demo' visit),
    a Post folder is required. Different from the demo-only case above."""
    pics = _make_pics(tmp_path, filled=("Initial", "Demo"))
    missing = check_photos(pics, raw_text="Joe: 1 St (Post Demo) Cesar")
    assert "Post pics" in missing


def test_mold_after_treats_post_mold_folder_as_satisfaction(tmp_path):
    """'Mold After' / 'Post Mold' on the dispatch line IS the post-mold
    stage — not a request for generic Mold pics on top of generic Post
    pics. A folder matching 'Post Mold' or 'Mold After' clears it."""
    pics = _make_pics(tmp_path, filled=("Initial", "Mold After"))
    missing = check_photos(pics, raw_text="Joe: 1 St (Mold After/Demo) Cesar")
    # Generic Mold pics should NOT fire — we're past the mold stage.
    assert "Mold pics" not in missing
    # Generic Post pics should NOT fire — Mold After IS the post stage.
    assert "Post pics" not in missing
    # Mold After pics should NOT fire — the Mold After folder satisfies it.
    assert "Mold After pics" not in missing


def test_mold_after_without_folder_flags_post_mold_pics(tmp_path):
    """Same setup as Buchanan — 'Mold After/Demo' activity, no
    post-mold/mold-after folder yet. The audit should flag a single
    Mold After pics finding (not double-count Mold + Post)."""
    pics = _make_pics(tmp_path, filled=("Initial", "Demo"))
    missing = check_photos(pics, raw_text="Joe: 1 St (Mold After/Demo) Cesar")
    assert "Mold After pics" in missing
    assert "Mold pics" not in missing
    assert "Post pics" not in missing


def test_mold_prep_requires_both_prep_and_post_prep(tmp_path):
    pics = _make_pics(tmp_path, filled=("Initial",))
    missing = check_photos(pics, raw_text="Joe: 1 St (Mold Prep) Cesar")
    assert "Mold Prep pics" in missing
    assert "Mold After pics" in missing
    # Generic 'Mold pics' must NOT also fire when prep is mentioned —
    # the prep check covers the mold side.
    assert "Mold pics" not in missing


def test_mold_prep_no_double_count_when_only_prep_present(tmp_path):
    """Having a Mold Prep folder shouldn't satisfy Post Mold Prep —
    they're anchored separately via ^mold\\s*prep vs ^post\\s*mold."""
    pics = _make_pics(tmp_path, filled=("Initial", "Mold Prep"))
    missing = check_photos(pics, raw_text="Joe: 1 St (Mold Prep) Cesar")
    assert "Mold Prep pics" not in missing
    assert "Mold After pics" in missing


def test_general_mold_clearance_flags_mold_pics(tmp_path):
    """'Mold Clearance' on the dispatch line means general mold work,
    NOT mold prep — so the audit should ask for a Mold folder, not
    a Mold Prep folder."""
    pics = _make_pics(tmp_path, filled=("Initial",))
    missing = check_photos(
        pics, raw_text="Joe: 1 St (Mold Clearance) Cesar")
    assert "Mold pics" in missing
    # Prep checks must NOT fire — the run doesn't mention prep at all.
    assert "Mold Prep pics" not in missing
    assert "Mold After pics" not in missing


def test_abatement_in_raw_text_flags_abatement_pics(tmp_path):
    pics = _make_pics(tmp_path, filled=("Initial",))
    missing = check_photos(
        pics, raw_text="Joe: 1 St (Abatement) Cesar")
    assert "Abatement pics" in missing


def test_water_only_job_doesnt_demand_demo_or_mold(tmp_path):
    """Sanity: a plain water job shouldn't surface demo/mold/abatement."""
    pics = _make_pics(tmp_path, filled=("Initial",))
    missing = check_photos(pics, raw_text="Joe: 1 St (water) Cesar")
    assert "Demo pics" not in missing
    assert "Mold pics" not in missing
    assert "Mold Prep pics" not in missing
    assert "Abatement pics" not in missing
    assert "Post pics" not in missing


def test_log_rows_path_still_works(tmp_path):
    """The pre-existing job_notes path passed log_rows; it must still
    drive the same stage detection."""
    pics = _make_pics(tmp_path, filled=("Initial",))
    log_rows = [("4/29", "Wed", "Demo work today", "Cesar")]
    missing = check_photos(pics, log_rows=log_rows)
    assert "Demo pics" in missing


def test_empty_demo_folder_still_counts_as_missing(tmp_path):
    """A Demo folder with no photos in it is treated as missing —
    matches the _has_files() gate inside cat_filled."""
    pics = _make_pics(tmp_path, filled=("Initial",), empty=("Demo",))
    missing = check_photos(pics, raw_text="Joe: 1 St (Demo) Cesar")
    assert "Demo pics" in missing
