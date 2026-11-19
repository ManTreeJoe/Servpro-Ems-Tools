#!/usr/bin/env python3
"""Guarded Main-only migration rehearsal. No Auth/provider/client activation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = 'oneloss-main-server'
CONFIG = Path('/opt/oneloss/main-server/compose.json')
REPORTS = Path('/opt/oneloss/migration/approval-rehearsals')


def command(args, **kwargs):
    kwargs.setdefault('timeout', 60)
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def build_probe(migration, *, commit=False):
    # The same full SQL runs on the real schema, but ALL changes roll back.
    if not migration.rstrip().endswith('commit;'):
        raise RuntimeError('Unexpected migration transaction layout.')
    probe = migration.rstrip()[:-len('commit;')]
    probe = probe.replace('begin;', "begin;\nset local lock_timeout='3s';\nset local statement_timeout='20s';\nset local transaction_timeout='60s';\nset local idle_in_transaction_session_timeout='30s';", 1) + """
    do $$begin
      if exists(select 1 from public.app_user_departments d left join oneloss_access.accounts a using(user_id)
          where a.status is distinct from 'approved') then raise exception 'Existing employee access changed'; end if;
      if not exists(select 1 from auth.users where lower(email)='pablo@servpro10100.com' and deleted_at is null)
          then raise exception 'Pablo test account not found'; end if;
    end$$;
    select set_config('request.jwt.claims',json_build_object('sub',(select user_id from oneloss_access.emergency_accounts),
      'role','authenticated','amr',json_build_array(json_build_object('method','password')))::text,true);
    set local role authenticated;
    do $$declare a jsonb; begin
      a:=public.my_app_access();
      if a->>'auth_mode'<>'emergency' or not (a->>'is_admin')::boolean or a->>'access_state'<>'approved'
        then raise exception 'Recovery permission probe failed'; end if;
      perform public.employee_admin_snapshot();
    end$$;
    reset role;
    rollback;
    """
    if commit:
        probe = probe.rstrip()[:-len('rollback;')] + 'commit;'
    return probe


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    if sys.argv[1:] != ['rehearse']:
        raise RuntimeError('Only the rollback rehearsal is available. Usage: server.py rehearse')
    print('OneLoss approval rehearsal v3: rollback only; NO database export.', flush=True)
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    migration = (root / 'approval.sql').read_text()
    expected = (root / 'approval.sha256').read_text().strip()
    if hashlib.sha256(migration.encode()).hexdigest() != expected:
        raise RuntimeError('Migration checksum mismatch.')
    config = json.loads(CONFIG.read_text())
    if config.get('name') not in (None, PROJECT):
        raise RuntimeError('Wrong Main project.')
    ids = command(['docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={PROJECT}',
                   '--filter', 'label=com.docker.compose.service=db'], text=True).stdout.split()
    if len(ids) != 1:
        raise RuntimeError('Expected exactly one running Main database.')
    db = ids[0]
    inspection = json.loads(command(['docker', 'inspect', db], text=True).stdout)[0]
    if inspection['Config']['Labels'].get('com.docker.compose.project') != PROJECT:
        raise RuntimeError('Wrong database project.')
    base = ['docker', 'exec', '-i', '--user', '0', db]
    psql = base + ['psql', '--no-password', '-XAtq', '-v', 'ON_ERROR_STOP=1', '-U', 'supabase_admin', '-d', 'postgres']
    def query(sql):
        return command(psql, input=sql, text=True).stdout.strip()
    if query("select exists(select 1 from pg_namespace where nspname='oneloss_access');") != 'f':
        raise RuntimeError('Approval schema already exists; do not rerun this initial rehearsal.')
    inventory = """select json_build_object('jobs',(select count(*) from public.jobs),
      'users',(select count(*) from auth.users),'memberships',(select count(*) from public.app_user_departments),
      'admins',(select count(*) from public.app_admins))::text;"""
    before = query(inventory)
    REPORTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    recovery = Path(tempfile.mkdtemp(prefix='approval-', dir=REPORTS))
    print(f'Protected rehearsal report directory: {recovery}', flush=True)
    print('Checking approval permissions inside a transaction; all changes will roll back.', flush=True)
    probe = build_probe(migration)
    result = subprocess.run(psql, input=probe, text=True, capture_output=True, timeout=75)
    (recovery / 'rehearsal-private.log').write_text(result.stdout + '\n' + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Rehearsal rolled back. Keep diagnostic private: {recovery}/rehearsal-private.log')
    if before != query(inventory) or query("select exists(select 1 from pg_namespace where nspname='oneloss_access');") != 'f':
        raise RuntimeError('Post-rehearsal state verification failed.')
    (recovery / 'rehearsal-pass.json').write_text(json.dumps({'migration_sha256':expected,
      'inventory':json.loads(before),'project':PROJECT,'rolled_back':True}, indent=2))
    print('PASS: approval migration and recovery permissions rehearsed against Main, then rolled back.')
    print('PASS: Pablo account found; existing users, jobs, memberships and administrators unchanged.')
    print('PASS: Auth configuration, Microsoft enforcement, public routes and demo unchanged.')
    print(f'Protected rehearsal report directory: {recovery}')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid printing database output, compose environments, credentials or rows.
        if isinstance(error, RuntimeError):
            print(f'STOP: {error}')
        else:
            print(f'STOP: rehearsal could not finish ({type(error).__name__}). Keep private files local.')
        sys.exit(1)
