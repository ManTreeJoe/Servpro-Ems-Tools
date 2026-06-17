"""SharePoint folder name → pics subfolder routing.

These cases mirror real-world tags the lead techs leave on SP folders.
Most-specific match must win so 'Post Mold Prep' doesn't collapse to
'Mold Prep pics' or 'Post pics'.
"""
import stages


def test_initial_inspection_folder():
    # Initial pics land in a plain "Initial" folder (no " pics" suffix);
    # audits still match because check_photos does a substring match on
    # 'initial'.
    assert stages.detect_sp_folder_subfolder(
        "Bridgette Miles - Initial 4-23-26") == "Initial"


def test_demo_folder():
    assert stages.detect_sp_folder_subfolder(
        "Smith Demo Day 1") == "Demo pics"


def test_mold_prep_folder():
    assert stages.detect_sp_folder_subfolder(
        "Jones - Mold Prep") == "Mold Prep pics"


def test_post_mold_prep_beats_mold_prep():
    # Post Mold Prep must win over plain Mold Prep — order in
    # _SP_FOLDER_PATTERNS guards this.
    assert stages.detect_sp_folder_subfolder(
        "Jones - Post Mold Prep") == "Post Mold Prep pics"


def test_post_demo_routes_to_post():
    assert stages.detect_sp_folder_subfolder(
        "Smith - Post Demo") == "Post pics"


def test_reinspection_folder():
    assert stages.detect_sp_folder_subfolder(
        "Smith Reinspection 5-1") == "Reinspection pics"


def test_bare_mold_routes_to_mold_prep():
    # Plain "mold" work in our process is the prep stage.
    assert stages.detect_sp_folder_subfolder(
        "Jones Mold Day 2") == "Mold Prep pics"


def test_mold_clearance_does_not_route_to_mold_prep():
    # The (?!\s*clear) lookahead must guard the bare-mold fallback.
    assert stages.detect_sp_folder_subfolder(
        "Jones Mold Clearance") == ""


def test_eq_pics_tag_does_not_block_stage_match():
    # Lead techs sometimes file equipment shots — the EQ tag shouldn't
    # stop us from routing to the correct stage subfolder.
    assert stages.detect_sp_folder_subfolder(
        "Mark E - Initial EQ pics") == "Initial"


def test_unrecognized_folder_returns_empty():
    assert stages.detect_sp_folder_subfolder("random folder") == ""


def test_empty_folder_returns_empty():
    assert stages.detect_sp_folder_subfolder("") == ""


def test_stage_label_consistency_with_pics_subfolder():
    # Most stage subfolders end with " pics" (e.g. "Demo pics", "Mold
    # Prep pics"). The one exception is Initial Inspection, which the
    # user prefers to name plain "Initial".
    for label, sub in stages.PICS_SUBFOLDER.items():
        if label == "Initial Inspection":
            assert sub == "Initial", \
                f"Initial Inspection should map to 'Initial', got {sub!r}"
        else:
            assert sub.endswith(" pics"), \
                f"{label!r} pics subfolder {sub!r} should end with ' pics'"


def test_needs_photos_covers_all_labels():
    # Every label in STAGES must have a NEEDS_PHOTOS entry.
    for label in stages.LABELS:
        assert label in stages.NEEDS_PHOTOS
