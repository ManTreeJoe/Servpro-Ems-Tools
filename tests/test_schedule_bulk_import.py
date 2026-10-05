from schedule_bulk_import import commands, match_job


JOBS=[{'job_id':'one','display_name':'Caldwell, Cornelius - Mercury','address':'123 Main Street'},
      {'job_id':'two','display_name':'Jones, Paul - AAA','address':'456 Pine Lane'}]


def test_reversed_name_matches_and_partial_names_do_not():
    assert match_job('Cornelius Caldwell: Demo',JOBS)[0]=='one'
    assert match_job('Caldwell: Demo',JOBS)[0] is None


def test_conflicting_and_shared_identities_stay_unlinked():
    assert match_job('Cornelius Caldwell: 456 Pine Lane',JOBS)[0] is None
    assert match_job('Cornelius Caldwell: Demo',JOBS+[dict(JOBS[0],job_id='duplicate')])[0] is None


def test_bulk_keeps_unmatched_and_waiting_without_fake_jobs():
    preview={'workspace':'IE','source_filename':'Run.docx','visits':[
        {'raw_text':'Unknown home: Demo','struck':False,'section':'work','queue':'scheduled','group':'Work To Be Performed','proposed_date':'2026-10-05','draft_id':'a','source_row_key':'key:1'},
        {'raw_text':'Paul Jones: waiting','struck':False,'section':'tbs_mitigation','queue':'tbs','group':'TBS Mitigation','proposed_date':None,'draft_id':'b','source_row_key':'key:2'},
        {'raw_text':'Crossed out','struck':True,'section':'work'}]}
    entries,skipped=commands(preview,JOBS)
    assert len(entries)==2 and len(skipped)==1
    assert entries[0]['visit']['job_id'] is None
    assert entries[0]['visit']['activities']==[{'label':'Demo','people':[]}]
    assert entries[1]['visit']['date'] is None
    assert entries[1]['visit']['job_id']=='two'
    assert commands(preview,JOBS)[0]==entries
