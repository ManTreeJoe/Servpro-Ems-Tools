"""Job Notes stage detection — the biggest source of false positives is
'Recon Services / Recon Board' (Trello handoff) being mistaken for actual
recon work. These tests lock in the action-required pattern so a future
regex tweak doesn't regress."""
from job_notes_gui import parse_stages, expected_files


def test_initial_inspection():
    assert "Initial Inspection" in parse_stages("Initial inspection 4/20/26")


def test_inspection_alone_is_initial():
    # 'inspection' (without 'initial') still maps to the initial stage
    assert "Initial Inspection" in parse_stages("Inspection scheduled")


def test_mold_prep():
    stages = parse_stages("Mold Prep work scheduled for Wednesday")
    assert "Mold Prep" in stages


def test_demo():
    assert "Demo" in parse_stages("demo on Friday with Vince")


def test_recon_handoff_does_NOT_match():
    text = ("Zac via Automation: This insured is interested in Recon Services. "
            "Sent over card to Recon Board.")
    assert "Recon" not in parse_stages(text)


def test_recon_actual_work_matches():
    assert "Recon" in parse_stages("Recon work in progress 4/30")
    assert "Recon" in parse_stages("Job moved into recon today")
    assert "Recon" in parse_stages("Recon scheduled for Monday")


def test_expected_files_for_demo():
    files = expected_files(["Demo"])
    assert "Demo pics" in files
    assert "Post pics" in files


def test_expected_files_initial_only():
    files = expected_files(["Initial Inspection"])
    assert "Initial pics" in files
    assert "Demo pics" not in files


def test_expected_files_canonical_order():
    # Files should follow STAGES order, not insertion order of arg
    files = expected_files(["Demo", "Initial Inspection"])
    # Initial should appear first since it's earlier in STAGES
    assert files.index("Initial pics") < files.index("Demo pics")
