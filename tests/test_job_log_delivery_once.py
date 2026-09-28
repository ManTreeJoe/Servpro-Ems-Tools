import job_workflow as workflow


def test_delivery_is_claimed_once_and_uncertain_post_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow,'DB_PATH',str(tmp_path/'queue.db'))
    queued = workflow.queue_job_log('job',{'entry_id':'entry'},'card','original')
    key = queued['operation_key']
    assert workflow.claim_delivery(key)
    assert not workflow.claim_delivery(key)
    workflow.fail(key,'Timed out after send')
    assert workflow.pending() == []
    assert workflow.status()['failed'] == 1


def test_repeated_queue_never_reopens_completed_post(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow,'DB_PATH',str(tmp_path/'queue.db'))
    queued = workflow.queue_job_log('job',{'entry_id':'entry'},'card','original')
    workflow.acknowledge(queued['operation_key'],external_id='')
    workflow.queue_job_log('job',{'entry_id':'entry'},'card','edited')
    assert workflow.pending() == []
