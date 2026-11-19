#!/usr/bin/env python3
"""Authorized pending/approval test for Pablo only. Never deletes an account."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

PROJECT = 'oneloss-main-server'
EMAIL = 'pablo@servpro10100.com'
REPORTS = Path('/opt/oneloss/migration/approval-user-tests')


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def change_sql(saved, restore=False):
    uid = str(uuid.UUID(saved['user_id']))
    original_revision = int(saved['revision'])
    expected_status = 'pending' if restore else 'approved'
    expected_revision = original_revision + (1 if restore else 0)
    next_status = 'approved' if restore else 'pending'
    action = 'operator_test_restore' if restore else 'operator_test_pending'
    departments = literal(json.dumps(saved['departments']))
    role = literal(saved['role'])
    old = literal(json.dumps(saved))
    expected_admin = 'true' if saved['is_admin'] else 'false'
    pending_check = '' if restore else f"""
    select set_config('request.jwt.claims',json_build_object('sub','{uid}',
      'role','authenticated','amr',json_build_array(json_build_object('method','oauth')))::text,true);
    set local role authenticated;
    do $$begin
      if public.my_app_access()->>'access_state'<>'pending'
         or exists(select 1 from public.jobs) then raise exception 'Pending admission check failed'; end if;
    end$$;
    reset role;
    """
    return f"""begin;
    set local lock_timeout='3s'; set local statement_timeout='15s'; set local transaction_timeout='30s';
    select pg_advisory_xact_lock(19632026,19112026);
    do $$declare a oneloss_access.accounts; actor uuid; begin
      select * into a from oneloss_access.accounts where user_id='{uid}'::uuid for update;
      if a.status is distinct from '{expected_status}' or a.revision is distinct from {expected_revision}
          or a.role is distinct from {role} then raise exception 'Account changed; stop and review'; end if;
      if not exists(select 1 from auth.users where id=a.user_id and lower(email)='{EMAIL}' and deleted_at is null)
          or exists(select 1 from oneloss_access.emergency_accounts where user_id=a.user_id)
          then raise exception 'Wrong or protected test account'; end if;
      if (select coalesce(jsonb_agg(department order by department),'[]'::jsonb)
          from public.app_user_departments where user_id=a.user_id) <> {departments}::jsonb
          or exists(select 1 from public.app_admins where user_id=a.user_id) <> {expected_admin}
          then raise exception 'Assignment changed; stop and review'; end if;
      select user_id into strict actor from oneloss_access.emergency_accounts;
      update oneloss_access.accounts set status='{next_status}', revision=revision+1,
        reviewed_at=now(),reviewed_by=actor where user_id=a.user_id;
      insert into oneloss_access.audit(actor,target,action,previous,current)
        values(actor,a.user_id,'{action}',{old}::jsonb,
          jsonb_build_object('status','{next_status}','role',a.role,'source','authorized_server_operator_test'));
    end$$;
    {pending_check}
    commit;"""


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo.')
    if sys.argv[1:] != ['pending'] and not (len(sys.argv)==3 and sys.argv[1] in ('verify','restore')):
        raise RuntimeError('Usage: pablo_test.py pending | verify REPORT_DIRECTORY | restore REPORT_DIRECTORY')
    os.umask(0o077)
    result = subprocess.run(['docker','ps','-q','--filter',f'label=com.docker.compose.project={PROJECT}',
        '--filter','label=com.docker.compose.service=db'],check=True,capture_output=True,text=True,timeout=30)
    ids = result.stdout.split()
    if len(ids)!=1:
        raise RuntimeError('Expected exactly one running Main database.')
    args = ['docker','exec','-i','--user','0',ids[0],'psql','--no-password','-XAtq','-v','ON_ERROR_STOP=1',
            '-U','supabase_admin','-d','postgres']
    def query(sql, report=None):
        result = subprocess.run(args,input=sql,text=True,capture_output=True,timeout=40)
        if result.returncode:
            if report:
                (report/'private-error.log').write_text(result.stderr)
            raise RuntimeError('Test command did not pass. Preserve the report directory and do not rerun blindly.')
        return result.stdout.strip()
    state = json.loads(query(f"""select json_build_object('user_id',u.id::text,'email',u.email,
      'status',a.status,'role',a.role,'revision',a.revision,
      'is_admin',exists(select 1 from public.app_admins where user_id=u.id),
      'recovery',exists(select 1 from oneloss_access.emergency_accounts where user_id=u.id),
      'departments',(select coalesce(jsonb_agg(department order by department),'[]'::jsonb)
        from public.app_user_departments where user_id=u.id))::text
      from auth.users u join oneloss_access.accounts a on a.user_id=u.id
      where lower(u.email)='{EMAIL}' and u.deleted_at is null;"""))
    if state['recovery'] or state['email'].lower()!=EMAIL:
        raise RuntimeError('Wrong or protected account; nothing changed.')
    if sys.argv[1]=='pending':
        if state['status']!='approved' or not state['role'] or not state['departments']:
            raise RuntimeError('Pablo is not currently approved and assigned. Do not repeat the pending step.')
        REPORTS.mkdir(parents=True,exist_ok=True,mode=0o700)
        report = Path(tempfile.mkdtemp(prefix='pablo-',dir=REPORTS))
        (report/'before.json').write_text(json.dumps(state,indent=2))
        print(f'Protected test report directory: {report}',flush=True)
        query(change_sql(state),report)
        print('PASS: only Pablo is pending; his account, jobs, role and franchise assignments were retained.')
        print(f"Restore by approving the saved role '{state['role']}' and franchise codes: {', '.join(state['departments'])}")
        print(f'To cancel the test: sudo python3 {Path(__file__).resolve()} restore {report}')
    else:
        report = Path(sys.argv[2]).resolve()
        if not report.is_relative_to(REPORTS.resolve()):
            raise RuntimeError('Use the protected Pablo test report directory.')
        marker = report/'before.json'
        if marker.is_symlink() or marker.stat().st_uid!=0 or marker.stat().st_mode & 0o077:
            raise RuntimeError('Test snapshot must be private and root-owned.')
        saved = json.loads(marker.read_text())
        if saved['user_id']!=state['user_id'] or saved['email'].lower()!=EMAIL:
            raise RuntimeError('Test snapshot does not match Pablo.')
        matches = all(state[key]==saved[key] for key in ('role','departments','is_admin'))
        if state['status']=='approved' and matches:
            (report/'restored-pass.json').write_text(json.dumps({'approved':True,'assignments_match':True}))
            print('PASS: Pablo is approved with his original role and franchise assignments.')
        elif sys.argv[1]=='restore' and matches:
            query(change_sql(saved,restore=True),report)
            print('PASS: pending test cancelled; Pablo has his original approved access again.')
        else:
            raise RuntimeError('Pablo is not yet restored to his original access. Do not overwrite another admin decision.')


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('STOP: '+str(error) if isinstance(error,RuntimeError)
              else f'STOP: test could not finish ({type(error).__name__}); keep private files local.')
        sys.exit(1)
