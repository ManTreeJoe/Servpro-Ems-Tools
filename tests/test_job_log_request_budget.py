import io
import urllib.error
import pytest
import supabase_client as sb


def test_interactive_database_calls_do_not_retry_and_restore_defaults(monkeypatch):
    calls=[]
    monkeypatch.setattr(sb,'creds',lambda:('https://fixture.invalid','fixture'))
    def fail(req,timeout):
        calls.append(timeout)
        raise urllib.error.HTTPError(req.full_url,503,'fixture',{},io.BytesIO(b'busy'))
    monkeypatch.setattr(sb.urllib.request,'urlopen',fail)
    monkeypatch.setattr(sb.time,'sleep',lambda _: pytest.fail('Interactive action retried'))
    with sb.interactive_requests():
        with pytest.raises(sb.SupabaseError): sb._raw('GET','/rest/v1/jobs')
    with pytest.raises(sb.SupabaseError): sb._raw('GET','/rest/v1/jobs',_max_retries=0)
    assert len(calls)==2
    assert calls[0] <= 5
    assert calls[1] == 30
