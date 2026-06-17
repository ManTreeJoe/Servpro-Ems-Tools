"""Activity detection from a run-doc line — drives whether photos are
needed and which folder names we expect."""
from daily_photos_gui import detect_activity


def test_demo_needs_photos():
    out = detect_activity("Demo on Friday with Vince", section="work")
    assert out["needs_photos"] is True
    assert "Demo" in out["labels"]
    assert "Demo" in out["expected"]
    assert "Post" in out["expected"]


def test_mold_prep_includes_post_folder():
    out = detect_activity("Mold Prep work scheduled")
    assert "Mold Prep" in out["expected"]
    assert "Post Mold Prep" in out["expected"]


def test_monitor_no_photos():
    out = detect_activity("Monitor only")
    assert out["needs_photos"] is False


def test_clearance_no_photos():
    out = detect_activity("Mold clearance pass")
    assert out["needs_photos"] is False


def test_new_loss_defaults_to_initial():
    out = detect_activity("", section="work", new_loss=True)
    assert "Initial" in out["labels"]
    assert out["needs_photos"] is True


def test_initial_inspection_explicit():
    out = detect_activity("Initial inspection 11am")
    assert "Initial Inspection" in out["labels"]
    assert "Initial" in out["expected"]


def test_unspecified_in_work_section_still_needs_photos():
    # When we don't recognize the activity but the line is in the work
    # section, default to needing photos so we don't silently skip a job.
    out = detect_activity("walkthrough recap", section="work")
    assert out["needs_photos"] is True


def test_monitor_section_overrides_when_no_match():
    out = detect_activity("checkin", section="monitor")
    assert out["needs_photos"] is False


def test_multi_activity_contents_and_demo():
    """Lines like '(Contents/Demo)' should expose BOTH labels so the
    folder-create UI surfaces what photos to expect from each."""
    out = detect_activity("(Contents/Demo) Robert/Vince", section="work")
    assert "Contents" in out["labels"]
    assert "Demo" in out["labels"]
    assert "Contents" in out["expected"]
    assert "Demo" in out["expected"]
    assert out["needs_photos"] is True


def test_contents_alone_picks_up():
    out = detect_activity("Contents pack-out today", section="work")
    assert "Contents" in out["labels"]
    assert "Contents" in out["expected"]


def test_pack_out_implies_contents():
    out = detect_activity("Pack-out at 9am", section="work")
    assert "Pack-out" in out["labels"]
    assert "Contents" in out["expected"]
    assert "Pack-out" in out["expected"]


def test_reinspection_detected():
    out = detect_activity("Reinspection 2pm with FB", section="work")
    assert "Reinspection" in out["labels"]
    assert "Reinspection" in out["expected"]
    assert out["needs_photos"] is True


def test_teardown_implies_post_folder():
    out = detect_activity("Teardown today after demo", section="work")
    assert "Teardown" in out["labels"]
    assert "Post" in out["expected"]


def test_pack_in_implies_contents():
    out = detect_activity("Pack-in scheduled Friday", section="work")
    assert "Pack-in" in out["labels"]
    assert "Contents" in out["expected"]
    assert "Pack-in" in out["expected"]


def test_mold_clearance_not_mistaken_for_mold_prep():
    """Regression: 'Mold clearance pass' must NOT trigger Mold Prep folders.
    The audit and folder-create flow used to over-create Post Mold Prep
    folders for clearance-only days when this pattern overlapped."""
    out = detect_activity("Mold clearance pass scheduled")
    assert "Mold Prep" not in out["labels"]
    assert "Mold Prep" not in out["expected"]
    assert "Post Mold Prep" not in out["expected"]
    assert out["needs_photos"] is False


def test_unspecified_in_monitor_section_no_photos():
    """Monitor section default — even unrecognized lines get marked as
    no-photos so the folder-create flow doesn't ask for them."""
    out = detect_activity("standby today", section="monitor")
    assert out["needs_photos"] is False


def test_empty_line_in_work_section():
    # Empty line shouldn't crash; the work-section default kicks in.
    out = detect_activity("", section="work")
    assert out["needs_photos"] is True
    assert "Unspecified" in out["labels"]


def test_none_input():
    # None should be treated like empty string — no matches.
    out = detect_activity(None, section="monitor")
    assert out["needs_photos"] is False


def test_mold_prep_with_demo_combo():
    """Both detected; expected folders union without dups."""
    out = detect_activity("Mold prep + demo today", section="work")
    assert "Mold Prep" in out["labels"]
    assert "Demo" in out["labels"]
    # Both stages contribute their folders
    assert "Mold Prep" in out["expected"]
    assert "Demo" in out["expected"]
    assert "Post" in out["expected"]
    assert "Post Mold Prep" in out["expected"]
