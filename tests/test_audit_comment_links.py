import pytest
from logs_audit_storage import SharedAuditStorage
from audit_comment_links import EvidenceLinks,apply_links
from tests.test_logs_audit_storage import Database,Local


def setup():
    db=Database();storage=SharedAuditStorage(Local(),'IE',db)
    source={'c1':{'id':'c1','author':'Field Lead','date':'2026-04-08T20:14:00Z','text':'Inspection at 11am','source':'trello'},
            'c2':{'id':'c2','author':'Coordinator','date':'2026-04-08T21:00:00Z','text':'Initial note','source':'oneloss'}}
    return EvidenceLinks(storage,'IE',lambda c,d:source if c=='card' else {}),db


def test_link_edit_retarget_unlink_history_and_stale_write():
    api,db=setup()
    r=api.change('card','c1','field_note_posted_at','2026-04-08T20:14:00Z',None)
    assert api.read('card')==r
    assert apply_links({},r)['field_note_posted_at']=='2026-04-08T20:14:00Z'
    with pytest.raises(ValueError,match='another device'):
        api.change('card','c2','initial_note_sent_at','2026-04-08T21:00:00Z',None)
    r=api.change('card','c2','initial_note_sent_at','2026-04-08T21:00:00Z',r['version'])
    assert apply_links({},r)['missed_by']=='Coordinator'
    r=api.change('card','c1','ems_start','2026-04-07',r['version'],previous='field_note_posted_at')
    assert r['items']['field_note_posted_at'] is None
    r=api.change('card','c1','ems_start','',r['version'],remove=True)
    assert apply_links({'ems_start':'old'},r)['ems_start']==''
    assert len(db.history)==4


def test_no_invented_date_or_unverified_comment():
    api,_=setup()
    for value in ('','04/08/2026','2026-02-30'):
        with pytest.raises(ValueError):api.change('card','c1','contents_start',value,None)
    with pytest.raises(ValueError):api.change('card','missing','ems_billed','2026-04-08',None)
    with pytest.raises(ValueError):api.change('card','c1','initial_note_sent_at','2026-04-08T10:00',None)


def test_inspection_and_posting_saved_atomically_and_editable():
    api,db=setup()
    r=api.change('card','c1','field_note_posted_at','2026-04-08T20:14:00Z',None,
                 inspection='2026-04-08T11:00:00-07:00')
    fields=apply_links({},r)
    assert fields['inspection_at']=='2026-04-08T11:00:00-07:00'
    assert fields['field_note_posted_at']=='2026-04-08T20:14:00Z'
    r=api.change('card','c1','inspection_at','2026-04-08T11:30:00-07:00',r['version'])
    assert r['items']['field_note_posted_at']['value']==fields['field_note_posted_at']
    with pytest.raises(ValueError):
        api.change('card','c1','field_note_posted_at','2026-04-09T20:14:00Z',r['version'],inspection='invalid')
    assert api.read('card')==r
