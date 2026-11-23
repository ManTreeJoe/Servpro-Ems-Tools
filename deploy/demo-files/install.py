#!/usr/bin/env python3
"""Apply only to positively identified demo container; rehearse transaction first."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=90, **kwargs).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('rehearse', 'apply'))
    parser.add_argument('--proof', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    os.umask(0o077)
    source = Path(__file__).resolve().parent
    sql = (source / 'schema.sql').read_text()
    digest = hashlib.sha256(sql.encode()).hexdigest()
    if sql.count('begin;') != 1 or not sql.rstrip().endswith('commit;'):
        raise RuntimeError('Unexpected transaction boundaries.')
    ids = run(['docker','ps','-q','--filter','label=com.docker.compose.project=oneloss-demo',
               '--filter','label=com.docker.compose.service=db']).split()
    if len(ids) != 1:
        raise RuntimeError('Expected one running demo database.')
    db = json.loads(run(['docker','inspect',ids[0]]))[0]
    if not any(m.get('Destination') == '/var/lib/postgresql/data' and m.get('Source','').startswith('/opt/oneloss/demo/')
               for m in db['Mounts']):
        raise RuntimeError('Wrong demo database storage location.')
    command = ['docker','exec','-i',ids[0],'psql','-XAtq','-v','ON_ERROR_STOP=1','-U','supabase_admin','-d','postgres']
    def query(text):
        return run(command, input=text).strip()
    if query("select to_regclass('public.platform_losses') is not null and to_regclass('public.foundation_memberships') is not null and to_regclass('public.platform_admins') is not null;") != 't':
        raise RuntimeError('Demo does not have expected platform schema.')
    if query("select to_regnamespace('demo_files_private') is null and not exists(select 1 from storage.buckets where id in ('job-files','form-templates'));") != 't':
        raise RuntimeError('File schema/buckets already exist. Do not rerun initial installer.')
    baseline = query("select json_build_object('losses',(select count(*) from public.platform_losses),'memberships',(select count(*) from public.foundation_memberships),'admins',(select count(*) from public.platform_admins))::text;")
    parent = Path('/opt/oneloss/migration/demo-files')
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.mode == 'apply':
        if not args.proof:
            raise RuntimeError('Supply --proof from successful rehearsal.')
        proof = args.proof.resolve()
        if not proof.is_relative_to(parent.resolve()) or proof.is_symlink():
            raise RuntimeError('Unexpected rehearsal proof path.')
        info = proof.stat()
        if info.st_uid != 0 or info.st_mode & 0o077:
            raise RuntimeError('Proof must be root-owned and private.')
        record = json.loads(proof.read_text())
        if record != {'schema_sha256': digest, 'demo_db_id': db['Id'], 'baseline': baseline, 'rolled_back': True}:
            raise RuntimeError('Rehearsal proof differs from current demo state/schema.')
    report = Path(tempfile.mkdtemp(prefix=args.mode + '-', dir=parent))
    (report / 'schema.sql').write_text(sql)
    (report / 'before-counts.json').write_text(baseline)
    print('Report directory:', report, flush=True)
    print('Demo-only ' + args.mode + '; no Main, Auth, routes, files or containers will be changed.', flush=True)
    sql = sql.replace('begin;', "begin;set local lock_timeout='5s';set local statement_timeout='60s';", 1)
    if args.mode == 'rehearse':
        sql = sql.rstrip()[:-len('commit;')] + 'rollback;'
    try:
        run(command, input=sql)
    except subprocess.CalledProcessError as error:
        (report / 'private-error.log').write_text(error.stderr or '')
        raise RuntimeError('SQL transaction failed and rolled back. Keep private diagnostic local: ' + str(report)) from None
    after = query("select json_build_object('losses',(select count(*) from public.platform_losses),'memberships',(select count(*) from public.foundation_memberships),'admins',(select count(*) from public.platform_admins))::text;")
    if after != baseline:
        raise RuntimeError('Existing row counts changed; inspect concurrent activity. Do not rerun.')
    if args.mode == 'rehearse':
        if query("select to_regnamespace('demo_files_private') is null;") != 't':
            raise RuntimeError('Rollback verification failed.')
        proof = report / 'rehearsal-pass.json'
        proof.write_text(json.dumps({'schema_sha256':digest,'demo_db_id':db['Id'],'baseline':baseline,'rolled_back':True}))
        print('PASS: demo schema DDL rehearsed and rolled back; existing job/access counts unchanged.')
        print('Proof:', proof)
    else:
        state = query("select count(*)=9 and bool_and(relrowsecurity) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname in ('demo_form_templates','demo_file_profiles','demo_profile_slots','demo_job_profiles','demo_job_form_slots','demo_job_files','demo_file_uploads','demo_slot_files','demo_file_events');")
        buckets = query("select count(*)=2 and bool_and(not public and file_size_limit=52428800) from storage.buckets where id in ('job-files','form-templates');")
        if state != 't' or buckets != 't':
            raise RuntimeError('Schema committed but verification requires review. Do not rerun.')
        (report / 'apply-pass.json').write_text(json.dumps({'schema_sha256':digest,'demo_db_id':db['Id']}))
        print('PASS: demo file schema, franchise starter profiles and two private buckets installed.')
        print('PASS: existing job/access counts unchanged; Main/live not targeted. Actual Storage API upload test and demo site integration remain pending.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('STOP:', str(error) if isinstance(error, RuntimeError) else type(error).__name__ + '; private output concealed.')
        raise SystemExit(1)
