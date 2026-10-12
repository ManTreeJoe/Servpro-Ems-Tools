from datetime import datetime, timedelta, timezone
import pytest
from audit_timing_dashboard import report, TARGETS
from logs_audit import FIELDS
from audit_comment_links import TARGETS as LINK_TARGETS


@pytest.mark.parametrize('seconds,expected', [(0,'on_time'),(1,'late'),(-1,'on_time')])
def test_each_sequential_deadline(seconds,expected):
    start=datetime(2026,10,9,8,tzinfo=timezone.utc)
    keys=['incoming_loss_at','insured_contacted_at','on_site_at','field_note_posted_at','initial_note_sent_at']
    fields={keys[0]:start.isoformat()}
    for key,minutes in zip(keys[1:],[30,240,60,60]):
        start+=timedelta(minutes=minutes,seconds=seconds)
        fields[key]=start.isoformat()
    row=report({'drafts':{'card':{'fields':fields}}})['cards'][0]
    assert row['outcomes']=={key:expected for key in TARGETS}
    assert all(key in FIELDS and key in LINK_TARGETS for key in keys)


def test_missing_arrival_is_not_inspection_and_contact_anchors_four_hours():
    fields={'incoming_loss_at':'2026-10-09T08:00:00-07:00','insured_contacted_at':'2026-10-09T08:30:00-07:00',
            'on_site_at':'2026-10-09T12:30:00-07:00','field_note_posted_at':'2026-10-09T13:30:00-07:00'}
    row=report({'drafts':{'card':{'fields':fields}}})['cards'][0]
    assert row['outcomes']['arrival']=='on_time'
    fields['inspection_at']=fields.pop('on_site_at')
    row=report({'drafts':{'card':{'fields':fields}}})['cards'][0]
    assert row['outcomes']['arrival']==row['outcomes']['field']=='unknown'
