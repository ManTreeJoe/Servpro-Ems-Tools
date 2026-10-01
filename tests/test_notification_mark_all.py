from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
import pytest
import trello_client as tc
from notifications_web import Api


@pytest.mark.parametrize('body', [b'', b'OK', b'{}'])
def test_successful_mark_all_does_not_require_json(body):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = body
    with patch.object(tc, '_creds', return_value=('fixture', 'fixture')), \
         patch('trello_mirror_reader.mark_write'), \
         patch.object(tc.urllib.request, 'urlopen', return_value=response) as request:
        assert Api().mark_all_read()['ok'] is True
        assert request.call_args.args[0].method == 'POST'
        assert '/notifications/all/read?' in request.call_args.args[0].full_url


@pytest.mark.parametrize('code', [401, 403, 429, 503])
def test_rejections_have_safe_actionable_errors(code):
    failure = HTTPError('https://example.test/?token=SECRET', code, 'SECRET', {}, None)
    with patch.object(tc, '_call', side_effect=failure):
        result = Api().mark_all_read()
    assert result['ok'] is False
    assert str(code) in result['error']
    assert 'SECRET' not in result['error']


def test_unknown_failure_is_not_reported_as_success_or_leaked():
    with patch.object(tc, '_call', side_effect=RuntimeError('token=SECRET')):
        result = Api().mark_all_read()
    assert result['ok'] is False and result.get('error')
    assert 'SECRET' not in result['error']
