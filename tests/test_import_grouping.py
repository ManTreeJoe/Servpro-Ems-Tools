"""Stage/date detection + grouping for the auto-splitting import filter."""
import import_grouping as ig


def test_detect_stage_real_names():
    assert ig.detect_stage("7_14_26 demo garage 10.jpg") == "Demo"
    assert ig.detect_stage("7_15 laundry demo  99.jpg") == "Demo"
    assert ig.detect_stage("7_16 monitor  3.jpg") == "Monitor"
    assert ig.detect_stage("7_17 post mitigation  42.jpg") == "Post"
    assert ig.detect_stage("mold prep kitchen.jpg") == "Mold Prep"
    assert ig.detect_stage("post mold prep 2.jpg") == "Post Mold Prep"
    assert ig.detect_stage("initial inspection.jpg") == "Initial"
    assert ig.detect_stage("reinspection 3.jpg") == "Reinspection"
    # No stage word → None (needs a manual pick).
    assert ig.detect_stage("7_14_26 laundry  3.jpg") is None


def test_specific_beats_generic():
    # "post mold prep" must NOT fall through to "Post" or "Mold Prep".
    assert ig.detect_stage("7_20 post mold prep 1.jpg") == "Post Mold Prep"
    # "mold prep" must NOT match bare "Mold".
    assert ig.detect_stage("mold prep 5.jpg") == "Mold Prep"


def test_detect_date():
    assert ig.detect_date("7_14_26 demo garage.jpg") == ("2026-07-14", "7/14/26")
    key, label = ig.detect_date("7_16 monitor 2.jpg")
    assert label == "7/16" and key == "0000-07-16"
    assert ig.detect_date("post mitigation.jpg") == (None, "")


def test_detect_date_companycam_monthname():
    # CompanyCam format: 'Jul 23 2026' with a time that must NOT be mistaken
    # for a date. The photo date (Jul 23), not the export date, wins.
    assert ig.detect_date(
        "Bathroom 1 Initial Inspection-10-Jul 23 2026 11_43am-UsMC.jpg"
    ) == ("2026-07-23", "7/23/26")
    assert ig.detect_date("July 4, 2026 demo.jpg") == ("2026-07-04", "7/4/26")
    assert ig.detect_date("Sep 9 26 monitor.jpg") == ("2026-09-09", "9/9/26")


def test_detect_date_iso():
    assert ig.detect_date("photos-2026-07-24-fy5B") == ("2026-07-24", "7/24/26")


def test_time_only_is_not_a_date():
    # '11_43am' alone (43 > 31) must not read as a date.
    assert ig.detect_date("photo 11_43am.jpg") == (None, "")


def test_detect_groups_mims_scenario():
    files = (
        [f"7_14_26 demo garage {i}.jpg" for i in range(12)]
        + [f"7_14_26 laundry {i}.jpg" for i in range(16)]      # no stage
        + [f"7_15 laundry demo {i}.jpg" for i in range(133)]
        + [f"7_16 monitor {i}.jpg" for i in range(23)]
        + [f"7_17 post mitigation {i}.jpg" for i in range(50)]
    )
    res = ig.detect_groups(files)
    assert res["multi"] is True
    assert set(res["stages"]) == {"Demo", "Monitor", "Post"}
    assert res["unassigned"] == 16                    # the plain laundry
    # Folders auto-split by stage; the undated/nostage laundry is its own
    # group with an empty folder for the user to assign.
    folders = {g["folder"] for g in res["groups"] if g["folder"]}
    assert folders == {"Demo", "Monitor", "Post"}
    # One tech-group per (day, stage): 7/14 Demo, 7/14 (unassigned laundry),
    # 7/15 Demo, 7/16 Monitor, 7/17 Post → 5 groups.
    assert len(res["groups"]) == 5


def test_single_stage_not_flagged_multi():
    res = ig.detect_groups([f"7_17 post mitigation {i}.jpg" for i in range(5)])
    assert res["multi"] is False
    assert res["stages"] == ["Post"]
