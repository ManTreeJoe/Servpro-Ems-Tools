from datetime import date
import pytest
from weekly_review import scope, review_key, evidence

def test_period_division_role_and_company_are_independent():
    base = scope({'start':'2026-09-07','end':'2026-09-11','review_role':'field','division':'EMS'},'IE')
    key = review_key('loss1',base)
    for field, value in [('end','2026-09-18'),('review_role','front_ops'),('division','CONTENTS'),('location','OC')]:
        assert review_key('loss1',{**base,field:value}) != key

def test_evidence_is_detached_from_live_changes():
    row = {'id':'a','divisions':[{'division':'EMS','stage':'active'}],'review_key':'internal'}
    saved = evidence(row)
    row['divisions'][0]['stage'] = 'closed'
    assert saved['divisions'][0]['stage'] == 'active'
    assert 'review_key' not in saved

def test_scope_defaults_and_validation():
    result=scope({'location':'OC'},'IE',date(2026,9,11))
    assert result['location']=='IE'
    assert result['start']=='2026-09-07'
    for values in [{'start':'bad'},{'start':'2026-09-12','end':'2026-09-11'},{'review_role':'admin'},{'division':'unknown'}]:
        with pytest.raises(ValueError): scope(values,'IE')
