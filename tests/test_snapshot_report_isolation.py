from pathlib import Path
import snapshot_web as sw


def test_generate_keeps_exact_card_and_does_not_write_job_log(monkeypatch, tmp_path):
    import snapshot_logic, snapshot_revisions, closeout_watcher
    records, drafted = [], []
    monkeypatch.setattr(sw.config, 'load', lambda: {'snapshot_output': str(tmp_path)})
    monkeypatch.setattr(snapshot_logic, 'render_snapshot', lambda *a, **kw: None)
    monkeypatch.setattr(snapshot_revisions, 'save_revision', lambda *a, **kw: records.append((a, kw)) or {'ok': True, 'revision': 1})
    monkeypatch.setattr(closeout_watcher, 'mark_drafted', drafted.append)
    def forbidden(*a, **kw):
        raise AssertionError('Snapshot must not resolve a name pin or write Job Log')
    monkeypatch.setattr(sw.persistence, 'get_trello_card_id', forbidden)
    monkeypatch.setattr(sw, 'sync_snapshot_logs_to_job_log', forbidden)
    result = sw.Api().generate({'insured':'Edited report heading', 'source_client':'Original job',
                               'card_id':'contents-card', 'division':'CONTENTS', 'logs':[]})
    assert result['ok'] and result['job_log_unchanged']
    assert records[0][0][0] == 'Original job'
    assert records[0][1]['card_id'] == 'contents-card'
    assert records[0][1]['source_refs']['division'] == 'CONTENTS'
    assert drafted == ['contents-card']


def test_history_is_scoped_to_exact_card_and_division(monkeypatch):
    import snapshot_revisions
    monkeypatch.setattr(snapshot_revisions, 'list_revisions', lambda *a, **kw: [
        {'card_id':'ems', 'source_refs':{'division':'EMS'}},
        {'card_id':'contents', 'source_refs':{'division':'CONTENTS'}}])
    result = sw.Api().snapshot_history('Job', 100, 'contents', 'CONTENTS')
    assert result['count'] == 1 and result['revisions'][0]['card_id'] == 'contents'


def test_no_edit_writeback_and_identity_survives_draft():
    js = (Path(__file__).parents[1]/'snapshot_web_assets/app.js').read_text(encoding='utf8')
    assert 'setTimeout(syncSnapshotJobLog' not in js
    assert 'source_client: state.sourceClient || insured' in js
    assert "state.sourceClient = d.sourceClient || d.insured || ''" in js
    assert "state.division = d.division || 'EMS'" in js
    assert not sw.Api().sync_snapshot_job_log('Job', [])['ok']
