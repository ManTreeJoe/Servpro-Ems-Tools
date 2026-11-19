import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'deploy/employee-access'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server = load('approval_server', ROOT / 'server.py')
with patch.dict(sys.modules, {'server': server}):
    installer = load('approval_installer', ROOT / 'apply.py')


@pytest.fixture
def install(monkeypatch, tmp_path):
    sql = 'begin;\ncreate schema example_only;\ncommit;\n'
    digest = hashlib.sha256(sql.encode()).hexdigest()
    (tmp_path / 'approval.sql').write_text(sql)
    (tmp_path / 'approval.sha256').write_text(digest)
    config = tmp_path / 'compose.json'
    config.write_text(json.dumps({'name':server.PROJECT}))
    reports = tmp_path / 'rehearsals'
    reports.mkdir()
    proof = reports / 'passed'
    proof.mkdir()
    marker = proof / 'rehearsal-pass.json'
    marker.write_text(json.dumps({'project':server.PROJECT,'rolled_back':True,
        'migration_sha256':digest,'inventory':{'users':8,'admins':2,'memberships':8}}))
    original_stat = Path.stat
    def private_marker_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == marker:
            values = list(result)
            values[0] = 0o100600
            values[4] = 0
            return type(result)(values)
        return result
    monkeypatch.setattr(Path, 'stat', private_marker_stat)
    monkeypatch.setattr(server, 'CONFIG', config)
    monkeypatch.setattr(server, 'REPORTS', reports)
    monkeypatch.setattr(installer, '__file__', str(tmp_path / 'apply.py'))
    monkeypatch.setattr(installer.os, 'geteuid', lambda:0, raising=False)
    monkeypatch.setattr(installer.os, 'umask', lambda value:None)
    monkeypatch.setattr(installer.sys, 'argv', ['apply.py','--rehearsal',str(proof)])
    env = []
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        query = kwargs.get('input', '')
        if args[:2] == ['docker','ps']:
            output = 'db rest auth'
        elif args[:2] == ['docker','inspect']:
            output = json.dumps([{'Id':key,'Config':{'Labels':{
                'com.docker.compose.project':server.PROJECT,'com.docker.compose.service':key},
                'Env':env if key=='rest' else []}} for key in ('db','rest','auth')])
        elif 'pg_namespace' in query: output = 'f'
        elif 'pg_db_role_setting' in query: output = ''
        elif 'md5(' in query: output = '{"admins":"same-admins","memberships":"same-assignments"}'
        elif 'pg_get_functiondef' in query: output = '[]'
        elif 'microsoft_only' in query: output = '{"microsoft_only":false,"approved":8,"recovery_admins":1}'
        else: output = '{"users":8,"admins":2,"memberships":8}'
        return subprocess.CompletedProcess(args,0,stdout=output,stderr='')
    monkeypatch.setattr(server, 'command', command)
    run = Mock(return_value=subprocess.CompletedProcess([],0,stdout='',stderr=''))
    monkeypatch.setattr(installer.subprocess, 'run', run)
    return tmp_path, marker, env, calls, run


def test_install_requires_matching_rehearsal_and_preserves_configuration(install):
    root, _, _, calls, run = install
    installer.main()
    sql = run.call_args.kwargs['input']
    assert sql.rstrip().endswith('commit;')
    assert "set local transaction_timeout='60s'" in sql
    assert not any('pg_dump' in args or 'restart' in args or 'compose' in args for args in calls)
    assert len(list(root.rglob('install-pass.json'))) == 1
    result = json.loads(next(root.rglob('install-pass.json')).read_text())
    assert result['state']['microsoft_only'] is False


def test_mismatched_rehearsal_never_applies(install):
    _, marker, _, _, run = install
    proof = json.loads(marker.read_text())
    proof['migration_sha256'] = 'not-the-tested-migration'
    marker.write_text(json.dumps(proof))
    with pytest.raises(RuntimeError, match='does not match'):
        installer.main()
    run.assert_not_called()


def test_conflicting_rest_guard_stops_before_mutation(install):
    _, _, env, _, run = install
    env.append('PGRST_DB_PRE_REQUEST=existing_security_guard')
    with pytest.raises(RuntimeError, match='incompatible'):
        installer.main()
    run.assert_not_called()


def test_failed_install_does_not_record_success(install):
    root, _, _, _, run = install
    run.return_value = subprocess.CompletedProcess([],1,stdout='',stderr='concealed')
    with pytest.raises(RuntimeError, match='Install did not pass'):
        installer.main()
    assert not list(root.rglob('install-pass.json'))


def test_shared_transaction_builder_defaults_to_rollback():
    sql = 'begin;\nselect 1;\ncommit;'
    assert server.build_probe(sql).rstrip().endswith('rollback;')
    assert server.build_probe(sql, commit=True).rstrip().endswith('commit;')
