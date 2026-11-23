#!/usr/bin/env python3
"""Demo-only metadata preflight. No data rows, credentials or mutations."""
import json
import os
from pathlib import Path
import subprocess


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    ids = command(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=oneloss-demo',
                   '--filter', 'label=com.docker.compose.service=db']).split()
    if len(ids) != 1:
        raise RuntimeError('Expected one running demo database. Nothing changed.')
    db = json.loads(command(['docker', 'inspect', ids[0]]))[0]
    if not any(m.get('Destination') == '/var/lib/postgresql/data'
               and m.get('Source', '').startswith('/opt/oneloss/demo/') for m in db.get('Mounts', [])):
        raise RuntimeError('Demo database mount requires review. Nothing changed.')
    query = """
    begin read only;
    select json_build_object(
      'columns', (select coalesce(json_agg(row_to_json(c)), '[]') from (
        select table_schema,table_name,column_name,data_type,is_nullable,column_default
        from information_schema.columns where table_schema='public' and
        (table_name in ('jobs','app_admins','app_user_departments','foundation_companies',
          'foundation_franchises','foundation_memberships','platform_losses','foundation_jobs',
          'platform_admins','job_profiles','job_note_templates') or
          table_name like '%form%' or table_name like '%document%' or table_name like '%file%')
        order by table_name,ordinal_position) c),
      'functions', (select coalesce(json_agg(row_to_json(f)), '[]') from (
        select n.nspname as schema,p.proname as name,pg_get_function_identity_arguments(p.oid) as args,
          pg_get_functiondef(p.oid) as definition
        from pg_proc p join pg_namespace n on n.oid=p.pronamespace
        where n.nspname in ('public','oneloss_access') and p.proname in
          ('my_app_access','my_departments','is_app_admin','can_access_job','is_platform_admin')) f),
      'policies', (select coalesce(json_agg(row_to_json(p)), '[]') from (
        select schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check
        from pg_policies where (schemaname='storage' and tablename='objects') or
        (schemaname='public' and tablename in ('jobs','platform_losses','foundation_jobs',
          'foundation_memberships','foundation_franchises','job_profiles'))) p),
      'buckets', (select coalesce(json_agg(json_build_object('id',id,'public',public,
         'file_size_limit',file_size_limit,'allowed_mime_types',allowed_mime_types)), '[]') from storage.buckets)
    );
    rollback;
    """
    raw = command(['docker', 'exec', '-i', ids[0], 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
                   '-U', 'supabase_admin', '-d', 'postgres', '-c', query])
    data = json.loads(raw.strip())
    data['project'] = 'oneloss-demo'
    storage_ids = command(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=oneloss-demo',
                           '--filter', 'label=com.docker.compose.service=storage']).split()
    if len(storage_ids) == 1:
        storage = json.loads(command(['docker', 'inspect', storage_ids[0]]))[0]
        env = dict(v.split('=', 1) for v in storage['Config']['Env'] if '=' in v)
        data['storage'] = {'image': storage['Config']['Image'],
          'settings': {k: env[k] for k in ('STORAGE_BACKEND','FILE_SIZE_LIMIT','FILE_STORAGE_BACKEND_PATH') if k in env},
          'mounts': [{'source': m.get('Source'), 'destination': m.get('Destination')}
                     for m in storage['Mounts'] if m.get('Destination') == '/var/lib/storage']}
    output = Path('/home/nathan/oneloss-demo-files-preflight.json')
    os.umask(0o077)
    if output.is_symlink():
        raise RuntimeError('Unexpected output symlink.')
    output.write_text(json.dumps(data, indent=2))
    os.chmod(output, 0o600)
    import pwd
    user = pwd.getpwnam('nathan')
    os.chown(output, user.pw_uid, user.pw_gid)
    print('PASS: demo schema/storage metadata exported; no customer records or credentials included.')
    print('Main/live, demo data and services unchanged. Metadata file:', output)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('STOP:', str(error) if isinstance(error, RuntimeError) else type(error).__name__ + '; private output concealed.')
        raise SystemExit(1)
