import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('auth_rollout',Path(__file__).resolve().parents[1]/'deploy/employee-access/auth_rollout.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def existing():
    return {'GOTRUE_EXTERNAL_AZURE_ENABLED':'true','GOTRUE_EXTERNAL_EMAIL_ENABLED':'true',
        'GOTRUE_EXTERNAL_AZURE_CLIENT_ID':module.CLIENT,
        'GOTRUE_EXTERNAL_AZURE_URL':f'https://login.microsoftonline.com/{module.TENANT}',
        'GOTRUE_SITE_URL':'https://app.oneloss.work','API_EXTERNAL_URL':'https://api.oneloss.work',
        'GOTRUE_URI_ALLOW_LIST':'https://app.oneloss.work/auth/finish',
        'GOTRUE_EXTERNAL_AZURE_SECRET':'unchanged-test-secret','GOTRUE_SMTP_PASS':'unchanged-test-mail'}


def test_stage_preserves_recovery_secrets_redirects_and_old_password_access():
    original=existing();result=module.plan_environment(original,'stage')
    assert result['GOTRUE_EXTERNAL_EMAIL_ENABLED']=='true'
    assert result['GOTRUE_EXTERNAL_AZURE_SECRET']==original['GOTRUE_EXTERNAL_AZURE_SECRET']
    assert result['GOTRUE_SMTP_PASS']==original['GOTRUE_SMTP_PASS']
    assert 'GOTRUE_HOOK_PASSWORD_VERIFICATION_ATTEMPT_ENABLED' not in result
    assert result['GOTRUE_HOOK_BEFORE_USER_CREATED_ENABLED']=='true'
    assert result['GOTRUE_DISABLE_SIGNUP']=='false'
    assert result['GOTRUE_URI_ALLOW_LIST'].split(',')==['https://app.oneloss.work/auth/finish',module.WEB_RETURN,module.DESKTOP_RETURN]
    assert original==existing()


def test_enforcement_enables_only_the_reviewed_password_hook():
    result=module.plan_environment(existing(),'enforce')
    assert result['GOTRUE_HOOK_PASSWORD_VERIFICATION_ATTEMPT_ENABLED']=='true'
    assert result['GOTRUE_HOOK_PASSWORD_VERIFICATION_ATTEMPT_URI']=='pg-functions://postgres/oneloss_access/password_verification'


@pytest.mark.parametrize('change',[
    {'GOTRUE_EXTERNAL_AZURE_URL':'https://login.microsoftonline.com/common'},
    {'GOTRUE_EXTERNAL_EMAIL_ENABLED':'false'},
    {'GOTRUE_EXTERNAL_GOOGLE_ENABLED':'true'},
    {'API_EXTERNAL_URL':'https://demo-api.oneloss.work'},
])
def test_wrong_tenant_provider_or_environment_fails_closed(change):
    with pytest.raises(RuntimeError):module.plan_environment(existing()|change,'stage')


def test_container_verification_ignores_only_auth_recreation():
    def row(service,identity):return {'Id':identity,'Config':{'Labels':{'com.docker.compose.service':service}}}
    before=[row('auth','old-auth'),row('db','same-db'),row('rest','same-rest')]
    after=[row('auth','new-auth'),row('db','same-db'),row('rest','same-rest')]
    assert module.unrelated_ids(before)==module.unrelated_ids(after)
    after[1]['Id']='different-db'
    assert module.unrelated_ids(before)!=module.unrelated_ids(after)
