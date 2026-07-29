"""active_job_base descends into the active claim for multi-claim jobs.

Regression for the scope-PDF scattering: saving against a multi-claim job
root (e.g. "Mansolino Sayra" with 1st Claim / 2nd Claim subfolders) must
land deterministically under the highest-numbered claim, not the shared
job root or a nondeterministic DOCS."""
import os

from audit_logic import active_job_base


def test_descends_to_highest_claim(tmp_path):
    root = tmp_path / "Mansolino Sayra"
    (root / "1st Claim").mkdir(parents=True)
    (root / "2nd Claim (Kitchen)").mkdir()
    assert active_job_base(str(root)) == str(root / "2nd Claim (Kitchen)")


def test_single_claim_job_unchanged(tmp_path):
    """A normal job (no Nth-Claim subfolders) resolves to itself."""
    root = tmp_path / "Smith John"
    (root / "EMS").mkdir(parents=True)
    (root / "PICS").mkdir()
    assert active_job_base(str(root)) == str(root)


def test_missing_path_returned_as_is(tmp_path):
    nope = str(tmp_path / "does_not_exist")
    assert active_job_base(nope) == nope


def test_claim_sub_asset_not_treated_as_claim(tmp_path):
    """A "Second Claim Photos" sub-asset must NOT count as a claim folder."""
    root = tmp_path / "Doe Jane"
    (root / "Second Claim Photos").mkdir(parents=True)
    assert active_job_base(str(root)) == str(root)
