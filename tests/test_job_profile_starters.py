from copy import deepcopy
import job_profiles
from job_profile_starters import starters


def test_trello_starters_cover_company_templates_and_regular_work():
    rows = starters()
    assert len(rows) == 29
    names = {r['name'] for r in rows}
    assert {'EMS - Residential', 'EMS - Commercial', 'Contents', 'EMS - State Farm',
            'EMS - Property Management', 'Fire - Property Management',
            'Greystar Property Management', 'PCM', 'Hyder & Company'} <= names
    for row in rows:
        assert not row['active']
        assert row['payer_type'] == 'any'
        assert row['division'] == 'Any'
        assert row['source_url'].startswith('https://trello.com/c/')
        job_profiles.normalize(dict(row, department='IE'))


def test_state_farm_specific_forms_are_separate_from_regular():
    rows = {r['name']:r for r in starters()}
    regular = rows['EMS - Residential']['required_items']
    special = rows['EMS - State Farm']['required_items']
    assert not any('STATE FARM' in x for x in regular)
    assert 'INITIAL - ADMIN · ATP' in regular
    assert 'INITIAL - ADMIN · STATE FARM ATP' in special
    assert 'INITIAL - ADMIN · STATE FARM ATR' in special
    assert 'INITIAL - ADMIN · ATP' not in special


def test_conditional_services_are_recommended_not_mandatory():
    row = next(r for r in starters() if r['name'] == 'FIRE - Residential')
    snap = job_profiles.snapshot(dict(row, department='IE'))
    optional = [r for r in snap['requirements'] if r['label'].startswith('If applicable')]
    assert optional
    assert all(r['importance'] == 'recommended' for r in optional)
    from job_progress import evaluate
    result = evaluate({'department':'IE', 'lifecycle_stage':'intake',
                       'metadata':{'applied_job_profiles':[snap]}})
    assert all(r['importance'] == 'recommended' for r in result['items']
               if r['label'].startswith('If applicable'))


def test_available_profiles_ignore_selectors_but_preserve_scope_and_snapshots():
    p = dict(starters()[0], department='IE', profile_id='one', active=True,
             payer_type='management', carrier_or_client='Unrelated', division='Recon')
    job = {'department':'IE', 'job_type':'self_pay', 'metadata':{}}
    assert job_profiles.suggestions(job, [p]) == []
    before = deepcopy(p)
    assert job_profiles.available(job, [p])[0]['recommended'] is False
    assert p == before
    assert job_profiles.available(job, [dict(p, department='OC')]) == []
    assert job_profiles.available(job, [dict(p, active=False)]) == []
    job['metadata'] = job_profiles.apply_to_job(job, p)
    assert job_profiles.available(job, [p]) == []
    assert job_profiles.available({}, [p]) == []
