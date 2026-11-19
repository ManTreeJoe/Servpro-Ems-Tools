"""Recovered 1.8.48 migration: scratch files and fake ACL commands only."""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import server_connection_migration as migration


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'whoami':
            return SimpleNamespace(stdout='"fixture","S-1-5-21-123"')
        assert args[0] == 'icacls'
        assert not (Path(args[1]) / 'config.json').exists()
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(migration, 'os', SimpleNamespace(name='nt', replace=os.replace))
    monkeypatch.setattr(migration.subprocess, 'run', run)
    return tmp_path / 'config.json', calls


def seed(path, url):
    value = {'supabase_url':url, 'supabase_anon_key':'fixture-old-public-key',
             'trello_token':'fixture-personal-token', 'companycam_api_token':'fixture-camera-token',
             'runs_dir':'fixture-run-folder', 'audit_base':'fixture-job-folder',
             'departments':{'IE':{'supabase_url':url,'supabase_anon_key':'fixture-key','trello_token':'fixture-token'}}}
    path.write_text(json.dumps(value), encoding='utf-8')
    return value


def test_existing_main_moves_preserves_paths_and_requires_new_session(scratch):
    path,calls=scratch
    before=seed(path,migration.OLD_URL)
    session=path.parent/'supabase_session.json'
    session.write_text('fixture-session',encoding='utf-8')
    assert migration.migrate(path)
    after=json.loads(path.read_text())
    assert after['supabase_url']==migration.SERVER_URL
    assert after['supabase_anon_key']==migration.PUBLIC_KEY
    assert after['departments']['IE']['supabase_url']==migration.SERVER_URL
    assert after['trello_token']==after['departments']['IE']['trello_token']==''
    for key in ('companycam_api_token','runs_dir','audit_base'):assert after[key]==before[key]
    assert after['trello_writes_paused'] is True
    assert not session.exists()
    backups=list(path.parent.glob('before-server-switch-*'))
    assert len(backups)==1
    assert json.loads((backups[0]/'config.json').read_text())==before
    assert (backups[0]/session.name).read_text()=='fixture-session'
    assert [c[0] for c in calls]==['whoami','icacls']
    assert '/inheritance:r' in calls[1]
    assert not migration.migrate(path)
    assert len(list(path.parent.glob('before-server-switch-*')))==1


def test_acl_failure_prevents_capture_and_changes(scratch,monkeypatch):
    path,_=scratch;seed(path,migration.OLD_URL);before=path.read_bytes()
    def fail(*a,**k):raise OSError('fixture ACL refusal')
    monkeypatch.setattr(migration.subprocess,'run',fail)
    with pytest.raises(OSError):migration.migrate(path)
    assert path.read_bytes()==before
    assert not list(path.parent.glob('before-server-switch-*/config.json'))


def test_replace_failure_restores_config_and_session(scratch,monkeypatch):
    path,_=scratch;seed(path,migration.OLD_URL);before=path.read_bytes()
    session=path.parent/'supabase_session.json';session.write_text('fixture-session')
    def fail(*a):raise OSError('fixture replace refusal')
    monkeypatch.setattr(migration.os,'replace',fail)
    with pytest.raises(OSError):migration.migrate(path)
    assert path.read_bytes()==before
    assert session.read_text()=='fixture-session'
    assert not path.with_name('config.server-migration.tmp').exists()


def test_custom_endpoint_is_untouched(scratch):
    path,calls=scratch;seed(path,'https://fixture.invalid');before=path.read_bytes()
    assert not migration.migrate(path)
    assert path.read_bytes()==before and calls==[]


def test_custom_franchise_refuses_migration(scratch):
    path,calls=scratch;value=seed(path,migration.OLD_URL)
    value['departments']['IE']['supabase_url']='https://fixture.invalid'
    path.write_text(json.dumps(value));before=path.read_bytes()
    with pytest.raises(RuntimeError,match='Custom franchise'):migration.migrate(path)
    assert path.read_bytes()==before and calls==[]


@pytest.mark.parametrize('dev,trial,expected',[(True,False,False),(False,True,False),(False,False,True)])
def test_only_main_startup_invokes_migration(monkeypatch,dev,trial,expected):
    # Execute only the actual config function, with no config/path imports.
    root=Path(__file__).parents[1]
    tree=ast.parse((root/'config.py').read_text(encoding='utf-8'))
    method=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_ensure_user_config')
    calls=[];monkeypatch.setattr(migration,'migrate',lambda p:calls.append(p))
    fake_os=SimpleNamespace(path=SimpleNamespace(isfile=lambda p:p=='fixture-user'))
    scope={'_paths':SimpleNamespace(IS_DEV=dev,IS_TRIAL=trial),'_os':fake_os,
           '_USER_CFG':'fixture-user','_DEFAULT_CFG':'fixture-missing','_MACHINE_RECOVERY_ATTEMPTED':False}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'config.py','exec'),scope)
    scope['_ensure_user_config']()
    assert bool(calls) is expected


def test_packaged_main_target_matches_migration():
    seed_config=json.loads((Path(__file__).parents[1]/'_packaging/config.json').read_text())
    if os.environ.get('LINGUAR_CI') == '1':
        assert seed_config == {'trello_token':'','companycam_api_token':'','appearance':'system'}
        return  # CI deliberately replaces the shipping seed before tests/build.
    assert seed_config['supabase_url']==migration.SERVER_URL
    assert seed_config['supabase_anon_key']==migration.PUBLIC_KEY
    assert seed_config['trello_writes_paused'] is True
    assert not seed_config.get('trello_token')
    assert not seed_config.get('companycam_api_token')


def test_recovered_rollout_pause_precedes_credentials(monkeypatch):
    import trello_client
    monkeypatch.setattr(trello_client.config,'load',lambda:{'trello_writes_paused':True})
    monkeypatch.setattr(trello_client,'_creds',lambda:pytest.fail('Credentials reached'))
    with pytest.raises(RuntimeError,match='posting is paused'):
        trello_client._call('/cards',method='POST')
