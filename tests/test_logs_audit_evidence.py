from logs_audit_evidence import timing, candidates, compare, billing_facts

def test_timing_boundary_missing_and_timezone():
    assert timing('2026-09-17T10:00:00-07:00','2026-09-17T11:00:00-07:00')['status']=='Yes'
    assert timing('2026-09-17T10:00:00-07:00','2026-09-17T11:01:00-07:00')['status']=='No'
    assert timing('','2026-09-17T11:00')['status']=='Unverified'
    assert timing('2026-09-17','2026-09-17')['status']=='Unverified'
    assert timing('2026-09-17T10:00','2026-09-17T09:00')['status']=='Unverified'
    assert timing('2026-09-17T10:00','2026-09-17T11:00Z')['status']=='Unverified'

def test_matching_claim_division_unit_and_names():
    card={'name':'EMS - Example Unit 101','desc':'Claim #: ABC123\nDivision: EMS'}
    others=[{'id':'right',**card},{'id':'wrong-unit',**card,'name':'EMS - Example Unit 102'},
            {'id':'name','name':'Example','desc':''}]
    result={m['card']['id']:m for m in candidates(card,others)}
    assert result['right']['strong']
    assert not result['wrong-unit']['strong']
    assert not result['name']['strong']

def ev(text):
    return {'card':{'name':'EMS - Example'},'comments':[{'id':'c','author':'Tonia','date':'2026-09-17','text':text}]}

def test_billing_does_not_infer_from_invoice_payment_or_posted_date():
    for text in ['Invoice created 6/1/26','Paid in full 6/1/26','Billed','Will be billed on 6/1/26','Not billed on 6/1/26']:
        assert not any(f['status']=='Billed' for f in billing_facts(ev(text)))
    assert billing_facts(ev('EMS billed on 6/1/26'))[0]['date']=='2026-06-01'

def test_conflicting_billing_retains_both_sources():
    result=compare(ev('EMS billed on 6/1/26'),ev('EMS billed on 7/1/26'))
    assert len(result['conflicts'])==1
    assert result['conflicts'][0]['logs']['source']['text']=='EMS billed on 6/1/26'
