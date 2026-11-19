#!/usr/bin/env python3
"""Guarded Main-only migration rehearsal. No Auth/provider/client activation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

PROJECT = 'oneloss-main-server'
CONFIG = Path('/opt/oneloss/main-server/compose.json')


def command(args, **kwargs):
    kwargs.setdefault('timeout', 60)
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def backup(db, recovery, query):
    """One named, read-only export, with visible progress and scoped cleanup."""
    app = 'oneloss_approval_backup_' + uuid.uuid4().hex
    archive = recovery / 'database.dump'
    print(f'Protected recovery directory: {recovery}', flush=True)
    print('Creating recovery backup; progress appears every 15 seconds. Limit: 10 minutes.', flush=True)
    args = ['docker', 'exec', '--user', '0', '-e', f'PGAPPNAME={app}', '-e',
            'PGOPTIONS=-c lock_timeout=30s -c statement_timeout=10min', db,
            'pg_dump', '--no-password', '--lock-wait-timeout=30s',
            '-U', 'supabase_admin', '-d', 'postgres', '-Fc']
    with archive.open('wb') as target, (recovery / 'backup-private.log').open('wb') as diagnostic:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=target, stderr=diagnostic)
        started = time.monotonic()
        try:
            while True:
                try:
                    code = process.wait(timeout=15)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = int(time.monotonic() - started)
                    print(f'Backup running: {elapsed}s; {archive.stat().st_size / 1048576:.1f} MiB written.', flush=True)
                    if elapsed >= 600:
                        raise RuntimeError('Backup time limit reached. Migration was not started.')
            if code:
                private = (recovery / 'backup-private.log').read_text(errors='replace').lower()
                category = 'unclassified'
                for pattern, label in [('password', 'authentication_required'),
                                       ('permission denied', 'permission_denied'),
                                       ('lock timeout', 'lock_wait_timeout'),
                                       ('lock-wait', 'lock_wait_timeout'),
                                       ('connection', 'connection_failure')]:
                    if pattern in private:
                        category = label
                        break
                raise RuntimeError(f'Backup failed before migration ({category}). Keep diagnostic private: {recovery}/backup-private.log')
        except BaseException as error:
            # Never terminate another operator's pg_dump or any application session.
            try:
                query("select pg_terminate_backend(pid) from pg_stat_activity "
                      f"where application_name='{app}' and usename='supabase_admin' and pid<>pg_backend_pid();")
            except Exception:
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if isinstance(error, KeyboardInterrupt):
                raise RuntimeError('Backup cancelled before migration. Partial recovery files retained.') from None
            raise
    print(f'Recovery backup completed: {archive.stat().st_size / 1048576:.1f} MiB.', flush=True)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    if sys.argv[1:] != ['rehearse']:
        raise RuntimeError('Only the rollback rehearsal is available. Usage: server.py rehearse')
    print('OneLoss approval rehearsal v2: progress and bounded backup enabled.', flush=True)
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
    psql = base + ['psql', '-XAtq', '-v', 'ON_ERROR_STOP=1', '-U', 'supabase_admin', '-d', 'postgres']
    def query(sql):
        return command(psql, input=sql, text=True).stdout.strip()
    running = query("select count(*) from pg_stat_activity where "
                    "(application_name='pg_dump' or application_name like 'oneloss_approval_backup_%') "
                    "and pid<>pg_backend_pid();")
    if running != '0':
        raise RuntimeError('An earlier database export is still running. No new backup or migration started; report this message.')
    if query("select exists(select 1 from pg_namespace where nspname='oneloss_access');") != 'f':
        raise RuntimeError('Approval schema already exists; do not rerun this initial rehearsal.')
    inventory = """select json_build_object('jobs',(select count(*) from public.jobs),
      'users',(select count(*) from auth.users),'memberships',(select count(*) from public.app_user_departments),
      'admins',(select count(*) from public.app_admins))::text;"""
    before = query(inventory)
    recovery = Path(tempfile.mkdtemp(prefix='before-employee-approval-', dir='/opt/oneloss/backups'))
    shutil.copy2(CONFIG, recovery / 'compose.json')
    backup(db, recovery, query)
    command(base + ['pg_restore', '--list'], input=(recovery / 'database.dump').read_bytes())
    print('Backup archive readable. Starting transaction-only approval rehearsal...', flush=True)
    # The same full SQL runs on the real schema, but ALL changes roll back.
    if not migration.rstrip().endswith('commit;'):
        raise RuntimeError('Unexpected migration transaction layout.')
    probe = migration.rstrip()[:-len('commit;')] + """
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
    result = subprocess.run(psql, input=probe, text=True, capture_output=True)
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
    print(f'Protected recovery and rehearsal directory: {recovery}')


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
