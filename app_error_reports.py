"""Best-effort, bounded diagnostics. Never send raw errors or call arguments."""
import functools
import hashlib
import inspect
import json
import os
import platform
import re
import threading
import time

import config
import paths
import supabase_client as sb

_lock = threading.Lock()
_seen = {}
_slots = threading.BoundedSemaphore(2)

_CONTEXT_FIELDS = {'job_name', 'job_id', 'card_id', 'division', 'source_board',
                   'source_list', 'destination_board', 'destination_list',
                   'destination_board_id', 'destination_list_id', 'tool',
                   'device_id', 'error_type', 'http_status'}


def clean_context(context):
    """Only explicit identity/location fields, never arbitrary API arguments."""
    if not isinstance(context, dict):
        return {}
    return {key: re.sub(r'[\x00-\x1f\x7f]', ' ', value).strip()[:240]
            for key, value in context.items()
            if key in _CONTEXT_FIELDS and isinstance(value, str) and value.strip()}


def action_context(method, args, kwargs):
    try:
        values = inspect.signature(method).bind(*args, **kwargs).arguments
        context = {key: values[key] for key in ('card_id', 'job_id', 'division') if key in values}
        if isinstance(values.get('client'), str):
            context['job_name'] = values['client']
        for param, key in (('board_id', 'destination_board_id'), ('list_id', 'destination_list_id')):
            if isinstance(values.get(param), str):
                context[key] = values[param]
        # Resolve labels from the account-scoped local snapshot only. No network
        # dependency, fuzzy name matching, or extra permissions on an error path.
        if context.get('card_id'):
            import pipeline_store
            for board in pipeline_store.load_board_cache().get('boards', []):
                for lane in board.get('lanes', []):
                    if lane.get('list_id') == context.get('destination_list_id'):
                        context.update(destination_board=board.get('name'), destination_list=lane.get('name'))
                    for card in lane.get('cards', []):
                        if card.get('card_id') == context['card_id']:
                            context.update(job_name=card.get('name') or card.get('client'),
                                           source_board=board.get('name'), source_list=lane.get('name'))
        return clean_context(context)
    except Exception:
        return clean_context(locals().get('context', {}))


def shape(panel, action, message, context=None):
    text = str(message or '')[:20000]
    code = re.search(r'\b(?:PGRST\d{3}|HTTP\s+(?:[45]\d\d|0)|[A-Za-z]+Error)\b', text)
    tables = re.findall(r'\bcrm_pipeline_(?:boards|lanes|cards|activity)\b', text)
    error_code = code.group(0).replace(' ', '_') if code else 'unclassified'
    if 'reference is linked to multiple jobs' in text.lower():
        error_code = 'reference_multiple_jobs'
    if 'card is not in accessible saved board data yet' in text.lower():
        error_code = 'card_not_accessible_in_saved_data'
    # Classify transport failures before their generic exception names. Never
    # upload exception bodies, URLs, SQL, credentials, or arbitrary arguments.
    lower = text.lower()
    if '10054' in lower or 'connection reset' in lower or 'forcibly closed' in lower:
        error_code = 'connection_reset'
    elif isinstance(message, TimeoutError) or 'timed out' in lower or 'timeout' in lower:
        error_code = 'request_timeout'
    elif error_code == 'HTTP_0' or 'name resolution' in lower or 'getaddrinfo failed' in lower:
        error_code = 'network_unreachable'
    elif 'job changed during refresh' in lower:
        error_code = 'refresh_superseded'
    elif isinstance(message, BaseException) and error_code == 'unclassified':
        kind = type(message).__name__
        if re.fullmatch(r'[A-Za-z_]{1,80}', kind):
            error_code = kind
    payload = {'panel': panel if re.fullmatch(r'[a-z_]{1,60}', str(panel)) else 'unknown',
            'action': action if re.fullmatch(r'[a-z_]{1,100}', str(action)) else 'unknown',
            'code': error_code,
            'table_name': tables[0] if tables else '',
            'cached': '(cached)' in text,
            'app_version': paths.VERSION,
            'channel': 'dev' if os.environ.get('LINGUAR_DEV_MODE') == '1' else 'main',
            'fingerprint': hashlib.sha256(text.encode()).hexdigest()}
    safe = clean_context(context)
    if safe:
        payload['context'] = safe
    return payload


def capture_failure(panel, action, error, context=None):
    """Record the original exception before callers substitute safe UI copy."""
    try:
        report(panel, action, error, context)
    except Exception:
        pass  # Diagnostics must never replace the caller's original result.


def report(panel, action, message, context=None):
    try:
        user = (sb.current_user() or {}).get('id')
        if not user: return False
        payload = shape(panel, action, message, context)
        detail = payload.setdefault('context', {})
        # Stable per computer, shared by Main/Dev, without uploading its hostname.
        node = platform.node()
        if node:
            detail['device_id'] = hashlib.sha256(('oneloss-device-v1:' + node).encode()).hexdigest()[:20]
        detail.setdefault('tool', str(action)[:100])
        if isinstance(message, BaseException):
            detail['error_type'] = re.sub(r'[^A-Za-z0-9_]', '', type(message).__name__)[:80]
            http_status = getattr(message, 'status', None)
            if isinstance(http_status, int) and 0 <= http_status <= 599:
                detail['http_status'] = str(http_status)
        payload['department'] = config.active_department()
        key = (user, payload['department'], panel, action, payload['fingerprint'],
               json.dumps(payload.get('context', {}), sort_keys=True))
        now = time.monotonic()
        with _lock:
            for old in list(_seen):
                if _seen[old] < now - 300: _seen.pop(old)
            if key in _seen or len(_seen) >= 100: return False
            if not _slots.acquire(blocking=False): return False
            _seen[key] = now
        try:
            token = sb.access_token()  # Capture identity before the background write.
            def send():
                try:
                    sb._raw('POST', '/rest/v1/rpc/report_app_error',
                            body={'p_report': payload}, token=token)
                except Exception:
                    pass  # Reporting never reports its own failures.
                finally:
                    _slots.release()
            threading.Thread(target=send, daemon=True).start()
        except Exception:
            _slots.release()
            return False
        return True
    except Exception:
        return False


def instrument(panel, action, method):
    @functools.wraps(method)
    def call(*args, **kwargs):
        def record(error):
            context = action_context(method, args, kwargs)
            if context:
                report(panel, action, error, context)
            else:
                report(panel, action, error)
        try:
            result = method(*args, **kwargs)
        except Exception as error:
            record(error)
            raise
        if isinstance(result, dict) and result.get('ok') is False and result.get('error'):
            record(result['error'])
        return result
    # pywebview strips the first parameter even for functions attached to
    # an instance; preserve the original bound-method introspection shape.
    signature = inspect.signature(method)
    call.__signature__ = signature.replace(parameters=[
        inspect.Parameter('self', inspect.Parameter.POSITIONAL_ONLY),
        *signature.parameters.values()])
    return call
