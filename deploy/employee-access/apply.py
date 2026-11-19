#!/usr/bin/env python3
"""Install the rehearsed Main approval SQL; leave Auth and enforcement unchanged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import server


def verified_proof(directory, expected):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(server.REPORTS.resolve()):
        raise RuntimeError('Rehearsal proof must be inside the protected rehearsal directory.')
    marker = directory / 'rehearsal-pass.json'
    if marker.is_symlink() or marker.stat().st_uid != 0 or marker.stat().st_mode & 0o077:
        raise RuntimeError('Rehearsal proof must be a private root-owned file.')
    proof = json.loads(marker.read_text())
    if (proof.get('project') != server.PROJECT or proof.get('rolled_back') is not True
            or proof.get('migration_sha256') != expected):
        raise RuntimeError('Rehearsal proof does not match this migration and Main project.')
    return proof


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    if len(sys.argv) != 3 or sys.argv[1] != '--rehearsal':
        raise RuntimeError('Usage: apply.py --rehearsal /opt/oneloss/migration/approval-rehearsals/approval-DIRECTORY')
    os.umask(0o077)
    print('OneLoss approval install: rehearsed SQL only; NO database export or Microsoft-only activation.', flush=True)
    root = Path(__file__).resolve().parent
    migration = (root / 'approval.sql').read_text()
    expected = (root / 'approval.sha256').read_text().strip()
    if hashlib.sha256(migration.encode()).hexdigest() != expected:
        raise RuntimeError('Migration checksum mismatch.')
    proof = verified_proof(sys.argv[2], expected)
    config_bytes = server.CONFIG.read_bytes()
    config = json.loads(config_bytes)
    if config.get('name') not in (None, server.PROJECT):
        raise RuntimeError('Wrong Main project.')
    ids = server.command(['docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={server.PROJECT}'], text=True).stdout.split()
    records = json.loads(server.command(['docker', 'inspect', *ids], text=True).stdout) if ids else []
    by_service = {record['Config']['Labels'].get('com.docker.compose.service'): record for record in records
                  if record['Config']['Labels'].get('com.docker.compose.project') == server.PROJECT}
    if any(service not in by_service for service in ('db', 'rest', 'auth')):
        raise RuntimeError('Main database, REST and Auth must already be running.')
    rest_env = dict(value.split('=', 1) for value in by_service['rest']['Config']['Env'] if '=' in value)
    if rest_env.get('PGRST_DB_CONFIG', 'true').lower() != 'true' or rest_env.get('PGRST_DB_PRE_REQUEST'):
        raise RuntimeError('REST has an incompatible pre-request override; nothing changed.')
    db = by_service['db']['Id']
    psql = ['docker', 'exec', '-i', '--user', '0', db, 'psql', '--no-password', '-XAtq',
            '-v', 'ON_ERROR_STOP=1', '-U', 'supabase_admin', '-d', 'postgres']
    def query(sql):
        return server.command(psql, input=sql, text=True).stdout.strip()
    if query("select exists(select 1 from pg_namespace where nspname='oneloss_access');") != 'f':
        raise RuntimeError('Approval schema already exists. Do not rerun this initial install.')
    previous_guard = query("""select coalesce((select split_part(value,'=',2)
      from pg_db_role_setting s join pg_roles r on r.oid=s.setrole,
      lateral unnest(s.setconfig) value where r.rolname='authenticator'
      and value like 'pgrst.db_pre_request=%'),'');""")
    if previous_guard:
        raise RuntimeError('An existing REST pre-request guard needs review; nothing changed.')
    inventory_sql = """select json_build_object('users',(select count(*) from auth.users),
      'admins',(select count(*) from public.app_admins),
      'memberships',(select count(*) from public.app_user_departments))::text;"""
    before = json.loads(query(inventory_sql))
    if any(before[key] != proof['inventory'][key] for key in before):
        raise RuntimeError('User/access counts changed since rehearsal; rerun the rollback rehearsal first.')
    fingerprint_sql = """select json_build_object(
      'admins',md5(coalesce((select jsonb_agg(to_jsonb(a) order by user_id)::text from public.app_admins a),'[]')),
      'memberships',md5(coalesce((select jsonb_agg(to_jsonb(d) order by user_id,department)::text from public.app_user_departments d),'[]'))
      )::text;"""
    before_access = query(fingerprint_sql)
    reports = server.REPORTS.parent / 'approval-installs'
    reports.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = Path(tempfile.mkdtemp(prefix='install-', dir=reports))
    # Small permission definitions only, not a database dump or customer records.
    definitions = query("""select coalesce(jsonb_agg(jsonb_build_object('name',p.proname,'definition',pg_get_functiondef(p.oid)) order by p.proname),'[]'::jsonb)::text
      from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public'
      and p.proname in ('my_app_access','my_departments','is_app_admin');""")
    (report / 'before-permission-functions.json').write_text(definitions)
    (report / 'before-access-fingerprints.json').write_text(before_access)
    (report / 'before-inventory.json').write_text(json.dumps(before))
    print(f'Protected install report directory: {report}', flush=True)
    print('Installing approval permissions; existing accounts remain approved and enforcement remains off...', flush=True)
    result = subprocess.run(psql, input=server.build_probe(migration, commit=True), text=True, capture_output=True, timeout=75)
    (report / 'install-private.log').write_text(result.stdout + '\n' + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Install did not pass. Do not rerun; keep diagnostic private: {report}/install-private.log')
    # From this point the transaction committed. Do not claim rollback if a later check fails.
    state = json.loads(query("""select json_build_object('microsoft_only',
      (select microsoft_only from oneloss_access.controls where singleton),
      'approved',(select count(*) from oneloss_access.accounts where status='approved'),
      'recovery_admins',(select count(*) from oneloss_access.emergency_accounts))::text;"""))
    after_ids = server.command(['docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={server.PROJECT}'], text=True).stdout.split()
    if (state['microsoft_only'] is not False or state['recovery_admins'] != 1
            or state['approved'] != before['users'] or before_access != query(fingerprint_sql)
            or sorted(ids) != sorted(after_ids) or server.CONFIG.read_bytes() != config_bytes):
        raise RuntimeError(f'SQL committed, but post-install verification needs review. Do not rerun. Report directory: {report}')
    (report / 'install-pass.json').write_text(json.dumps({'project':server.PROJECT,
      'migration_sha256':expected,'rehearsal_directory':str(Path(sys.argv[2]).resolve()),
      'inventory':before,'state':state}, indent=2))
    print('PASS: approval permissions installed; existing accounts, roles and franchise assignments preserved.')
    print('PASS: Microsoft-only enforcement remains OFF; current employee sign-ins still work.')
    print('PASS: Main container IDs and Auth configuration unchanged. Demo and public routes not targeted.')
    print(f'Protected install report directory: {report}')
    print('Next: verify normal login and actual recovery password, then test the updated apps and Pablo approval.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if isinstance(error, RuntimeError):
            print(f'STOP: {error}')
        else:
            print(f'STOP: install could not finish ({type(error).__name__}). Do not rerun; keep private files local.')
        sys.exit(1)
