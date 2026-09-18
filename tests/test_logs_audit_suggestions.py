from logs_audit_suggestions import suggest

def evidence(desc='',comments=None):
    return {'card':{'desc':desc},'checklists':[], 'comments':comments or []}

def test_explicit_fields_have_sources_and_dates():
    s=suggest(evidence('EMS estimator: Kim\nDate received: 6/8/26\nEMS billed: 2026-06-10'))
    assert s['job_date']['value']=='2026-06-08'
    assert s['ems_estimator']['value']=='Kim'
    assert s['ems_estimator']['sources'][0]['id']=='description'

def test_conflicting_values_do_not_autofill():
    s=suggest(evidence('EMS estimator: Kim',[{'id':'a','text':'EMS estimator: Sam','date':'2026-06-11','author':'A'}]))
    assert s['ems_estimator']['value'] is None
    assert s['ems_estimator']['conflict']
    assert len(s['ems_estimator']['sources'])==2

def test_keywords_not_dates_or_passes():
    s=suggest(evidence('Invoice created\nNot billed yet\nCheck pickup scheduled tomorrow\nInitial inspection completed'))
    assert s['ems_billed']['value'] is None
    assert s['job_date']['value'] is None
    assert s['initial_note']['value'] is None
    assert 'Not billed yet' in s['billing_evidence']['value']
    assert 'scheduled tomorrow' in s['payment_notes']['value']

def test_prior_audit_cannot_recycle_itself():
    s=suggest(evidence('',[{'id':'a','text':'EMS estimator: Kim\n[LH logs audit x]'}]))
    assert s['ems_estimator']['value'] is None

def test_loss_date_is_not_job_date():
    assert suggest(evidence('Date of loss: 6/1/26'))['job_date']['value'] is None

def test_job_date_only_uses_description_received_date():
    comments=[{'id':'note','author':'Test','date':'2026-09-17',
               'text':'Date received: 9/16/26'}]
    s=suggest(evidence('- **Date Recieved:** 9/10/2026',comments))['job_date']
    assert s['value']=='2026-09-10'
    assert not s['conflict']
    assert [source['id'] for source in s['sources']]==['description']
    assert suggest(evidence('',comments))['job_date']['value'] is None

def test_conflicting_description_received_dates_require_review():
    s=suggest(evidence('Date Received: 9/10/26\nDate Recieved: 9/11/26'))['job_date']
    assert s['value'] is None
    assert s['conflict']

def test_received_date_not_inspection_or_ambiguous_job_date():
    s=suggest(evidence('Received date: 6/1/26\nInitial inspection: 6/3/26\nJob date: 6/4/26'))
    assert s['job_date']['value']=='2026-06-01'
    s=suggest(evidence('Initial inspection: 6/3/26\nDate of loss: 6/2/26\nJob date: 6/4/26'))
    assert s['job_date']['value'] is None
    assert s['job_date']['sources']==[]

def test_est_audit_author_and_full_findings():
    s=suggest(evidence('',[{'id':'a','author':'Juan','date':'2026-05-18','text':'ESTAudit:\nNo documentation only ATP\nMissing scope'}]))
    assert s['ems_estimator']['value']=='Juan'
    assert 'Missing scope' in s['estimator_notes']['value']
    assert s['contents_estimator']['value'] is None

def test_tonia_comment_is_evidence_not_billing_confirmation():
    s=suggest(evidence('WC status: Closed',[{'id':'a','author':'Tonia Baca','date':'2026-07-07','text':'Partial Payment\nContents $100'}]))
    assert 'Partial Payment' in s['billing_evidence']['value']
    assert s['ems_billed']['value'] is None
    assert s['file_status']['value'] is None
    assert s['file_status']['manual']

def test_contents_activity_not_default_employee():
    s=suggest(evidence('',[{'id':'a','date':'2026-06-10','author':'Someone Else','text':'I have grabbed the contents job'}]))
    assert s['contents_estimator']['value']=='Someone Else'
    assert s['ems_estimator']['value'] is None

def test_explicit_timestamps_only_for_timing():
    s=suggest(evidence('Inspection completed: 2026-09-17T10:00:00-07:00\nInitial note sent: 2026-09-17T11:10:00-07:00'))
    assert s['initial_note']['value']=='No'
    s=suggest(evidence('Arrival Time: 10:00\nInitial note sent on time: Yes'))
    assert s['initial_note']['value'] is None
