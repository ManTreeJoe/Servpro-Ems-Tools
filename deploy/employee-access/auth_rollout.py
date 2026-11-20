#!/usr/bin/env python3
"""Stage Azure-only onboarding; activate Microsoft-only separately after team rollout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.parse
import urllib.request

CONFIG=Path('/opt/oneloss/main-server/compose.json')
PROJECT='oneloss-main-server'
TENANT='531a5c30-54e0-4f48-9fa1-b02116daeec9'
CLIENT='16bb79a9-cdb7-4cdd-abb4-962e419b5be7'
WEB_RETURN='https://app.oneloss.work/auth/microsoft'
DESKTOP_RETURN='http://127.0.0.1:43821/auth/microsoft/callback'


def plan_environment(env,mode):
    env=dict(env)
    if env.get('GOTRUE_EXTERNAL_AZURE_ENABLED','').lower()!='true' or env.get('GOTRUE_EXTERNAL_AZURE_CLIENT_ID')!=CLIENT:
        raise RuntimeError('Expected existing OneLoss Microsoft provider; nothing changed.')
    tenant=urllib.parse.urlsplit(env.get('GOTRUE_EXTERNAL_AZURE_URL',''))
    if tenant.hostname!='login.microsoftonline.com' or tenant.path.strip('/').split('/')[0]!=TENANT:
        raise RuntimeError('Microsoft must be restricted to the configured company tenant.')
    if env.get('GOTRUE_SITE_URL')!='https://app.oneloss.work' or env.get('API_EXTERNAL_URL')!='https://api.oneloss.work':
        raise RuntimeError('Wrong production Auth addresses.')
    if env.get('GOTRUE_EXTERNAL_EMAIL_ENABLED','').lower()!='true':
        raise RuntimeError('Existing recovery email/password provider must remain enabled.')
    if any(key.startswith('GOTRUE_EXTERNAL_') and key.endswith('_ENABLED') and value.lower()=='true'
           and key not in ('GOTRUE_EXTERNAL_AZURE_ENABLED','GOTRUE_EXTERNAL_EMAIL_ENABLED','GOTRUE_EXTERNAL_PHONE_ENABLED') for key,value in env.items()):
        raise RuntimeError('Another sign-in provider is enabled; review before enforcing Microsoft-only access.')
    env['GOTRUE_EXTERNAL_PHONE_ENABLED']='false'
    allowed=[value.strip() for value in env.get('GOTRUE_URI_ALLOW_LIST','').split(',') if value.strip()]
    for url in (WEB_RETURN,DESKTOP_RETURN):
        if url not in allowed:allowed.append(url)
    env['GOTRUE_URI_ALLOW_LIST']=','.join(allowed)
    env['GOTRUE_HOOK_BEFORE_USER_CREATED_ENABLED']='true'
    env['GOTRUE_HOOK_BEFORE_USER_CREATED_URI']='pg-functions://postgres/oneloss_access/before_user_created'
    env['GOTRUE_DISABLE_SIGNUP']='false'
    if mode=='enforce':
        env['GOTRUE_HOOK_PASSWORD_VERIFICATION_ATTEMPT_ENABLED']='true'
        env['GOTRUE_HOOK_PASSWORD_VERIFICATION_ATTEMPT_URI']='pg-functions://postgres/oneloss_access/password_verification'
    return env


def unrelated_ids(records):
    return {record['Id'] for record in records
            if record['Config']['Labels'].get('com.docker.compose.service')!='auth'}


def verify_phone_unused(count):
    if int(count)!=0:
        raise RuntimeError('Existing phone sign-in accounts require review; nothing changed.')


def run(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,timeout=120,**kwargs)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('stage','enforce'))
    parser.add_argument('--team-ready',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError('Run with sudo.')
    if args.mode=='enforce' and not args.team_ready:
        raise RuntimeError('Finish team rollout, then use enforce --team-ready. Nothing changed.')
    os.umask(0o077)
    original=CONFIG.read_bytes(); config=json.loads(original)
    if CONFIG.is_symlink() or config.get('name') not in (None,PROJECT):raise RuntimeError('Wrong Main configuration.')
    service=config['services']['auth']
    old_env=service.get('environment',{})
    if isinstance(old_env,list):old_env=dict(value.split('=',1) for value in old_env if '=' in value)
    new_env=plan_environment(old_env,args.mode)
    before_ids=run(['docker','ps','-q','--filter',f'label=com.docker.compose.project={PROJECT}'],text=True).stdout.split()
    records=json.loads(run(['docker','inspect',*before_ids],text=True).stdout)
    services={record['Config']['Labels'].get('com.docker.compose.service'):record for record in records}
    if any(name not in services for name in ('auth','db','rest')):raise RuntimeError('Main services must be running.')
    if str(CONFIG) not in services['auth']['Config']['Labels'].get('com.docker.compose.project.config_files','').split(','):
        raise RuntimeError('Running Main Auth uses a different configuration.')
    psql=['docker','exec','-i','--user','0',services['db']['Id'],'psql','--no-password','-XAtq','-v','ON_ERROR_STOP=1',
          '-U','supabase_admin','-d','postgres']
    def query(sql):return run(psql,input=sql,text=True).stdout.strip()
    if old_env.get('GOTRUE_EXTERNAL_PHONE_ENABLED','').lower()=='true':
        verify_phone_unused(query("select (select count(*) from auth.users where deleted_at is null and nullif(phone,'') is not null) + (select count(*) from auth.identities where provider='phone');"))
    if query("select to_regprocedure('oneloss_access.before_user_created(jsonb)') is not null and to_regprocedure('oneloss_access.password_verification(jsonb)') is not null;")!='t':
        raise RuntimeError('Install approval permissions first.')
    previous_flag=query('select microsoft_only from oneloss_access.controls where singleton;')
    if args.mode=='stage' and previous_flag!='f':raise RuntimeError('Already enforced; staging must not weaken it.')
    # Verify actual hook permissions without creating a user or changing a password.
    query("""begin;set local role supabase_auth_admin;
      do $$begin
      if oneloss_access.before_user_created('{"user":{"app_metadata":{"provider":"azure"}}}'::jsonb)<>'{}'::jsonb
        or oneloss_access.before_user_created('{"user":{"app_metadata":{"provider":"email"}}}'::jsonb)->'error'->>'http_code'<>'403'
        then raise exception 'Azure-only hook check failed';end if;
      if oneloss_access.password_verification(jsonb_build_object('user_id',
          (select user_id from oneloss_access.emergency_accounts),'valid',true))->>'decision'<>'continue'
        or oneloss_access.password_verification('{"user_id":"00000000-0000-0000-0000-000000000000","valid":true}'::jsonb)->>'decision'<>'reject'
        then raise exception 'Recovery-only password hook check failed';end if;end$$;
      rollback;""")
    if args.mode=='enforce':
        feed=Path('/opt/oneloss/updates/public/main/version.txt')
        info=json.loads(feed.read_text());version=info['version']
        if tuple(map(int,version.split('.')))<(1,8,49):raise RuntimeError('Publish Windows 1.8.49 or later first.')
        installer=feed.parent.parent/'downloads'/f'Linguar-Hub-Setup-{version}.exe'
        with installer.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=info.get('sha256'):
                raise RuntimeError('Published installer checksum did not pass.')
    parent=Path('/opt/oneloss/backups'); report=Path(tempfile.mkdtemp(prefix='before-microsoft-rollout-',dir=parent))
    (report/'compose.before.json').write_bytes(original)
    compose=['docker','compose','--project-name',PROJECT,'--project-directory',str(CONFIG.parent),'-f',str(CONFIG)]
    clean={key:value for key,value in os.environ.items() if not key.startswith('COMPOSE_')}
    def write_config(content):
        descriptor,name=tempfile.mkstemp(prefix='auth-config-',dir=CONFIG.parent)
        with os.fdopen(descriptor,'wb') as stream:stream.write(content)
        os.chmod(name,0o600);os.replace(name,CONFIG)
    def recreate():
        run(compose+['up','-d','--no-deps','--wait','--wait-timeout','90','--pull','never','auth'],env=clean)
    print(f'Protected Auth configuration recovery directory: {report}',flush=True)
    print('Updating only Main Auth. No database export; demo and other services stay in place.',flush=True)
    service['environment']=new_env
    changed=json.dumps(config,indent=2).encode()
    try:
        write_config(changed)
        run(compose+['config','--quiet'],env=clean)
        recreate()
        ids=run(compose+['ps','-q','auth'],env=clean,text=True).stdout.split()
        current=json.loads(run(['docker','inspect',*ids],text=True).stdout)[0]
        actual=dict(value.split('=',1) for value in current['Config']['Env'] if '=' in value)
        if any(actual.get(key)!=value for key,value in new_env.items() if key.startswith('GOTRUE_') or key=='API_EXTERNAL_URL'):
            raise RuntimeError('Running Auth configuration differs from the prepared settings.')
        addresses=[network.get('IPAddress') for network in current['NetworkSettings']['Networks'].values() if network.get('IPAddress')]
        if not addresses:raise RuntimeError('Auth network address unavailable.')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://{addresses[0]}:9999/settings',timeout=10) as response:settings=json.load(response)
        if settings.get('external',{}).get('azure') is not True or settings.get('external',{}).get('email') is not True:
            raise RuntimeError('Microsoft or recovery provider health verification failed.')
        if settings.get('external',{}).get('phone') is True:
            raise RuntimeError('Unused phone sign-in was not disabled.')
        after_ids=run(['docker','ps','-q','--filter',f'label=com.docker.compose.project={PROJECT}'],text=True).stdout.split()
        after_records=json.loads(run(['docker','inspect',*after_ids],text=True).stdout)
        if unrelated_ids(after_records)!=unrelated_ids(records):
            raise RuntimeError('An unrelated Main container changed during rollout.')
        if args.mode=='enforce':query('update oneloss_access.controls set microsoft_only=true where singleton;')
        expected='t' if args.mode=='enforce' else 'f'
        if query('select microsoft_only from oneloss_access.controls where singleton;')!=expected:
            raise RuntimeError('Enforcement flag verification failed.')
    except Exception as error:
        diagnostic={'error_type':type(error).__name__,'message':str(error) if isinstance(error,RuntimeError) else 'Inspect private command diagnostic.'}
        (report/'rollout-private.json').write_text(json.dumps(diagnostic))
        if getattr(error,'stderr',None):
            value=error.stderr
            (report/'command-private.log').write_bytes(value if isinstance(value,bytes) else value.encode())
        write_config(original)
        query(f"update oneloss_access.controls set microsoft_only={'true' if previous_flag=='t' else 'false'} where singleton;")
        recreate()
        raise RuntimeError(f'Auth rollout failed; previous configuration restored. Keep files private: {report}') from None
    (report/'rollout-pass.json').write_text(json.dumps({'mode':args.mode,'azure_signup_hook':True,
      'desktop_return_allowed':True,'web_return_allowed':True,'microsoft_only':args.mode=='enforce'}))
    print('PASS: Microsoft web/Windows returns configured; only Azure can create a new pending account.')
    print('PASS: recovery email/password provider retained; unrelated Main containers unchanged; demo not targeted.')
    print('PASS: Microsoft-only enforcement '+('ON; test actual recovery sign-in now.' if args.mode=='enforce' else 'OFF during team update rollout.'))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('STOP: '+str(error) if isinstance(error,RuntimeError) else f'STOP: Auth rollout could not finish ({type(error).__name__}); do not rerun blindly or share private files.')
        raise SystemExit(1)
