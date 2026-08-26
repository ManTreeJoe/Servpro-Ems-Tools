from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trial_preflight_checks_the_complete_v9_crm_schema():
    source = (ROOT / "trial_preflight.py").read_text(encoding="utf-8")
    assert 'Shared DB schema (v9 CRM)' in source
    assert 'crm_job_departments' in source
    assert 'crm_job_relationships' in source
    assert '009_crm_foundation.sql' in source


def test_trial_guide_requires_v9_before_job_workspace_trial():
    guide = (ROOT / "TRIAL_SETUP.md").read_text(encoding="utf-8")
    assert 'supabase/009_crm_foundation.sql' in guide
    assert 'Job Workspace' in guide
    assert 'PC A' in guide and 'PC B' in guide
