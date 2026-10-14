"""Best-effort, bounded diagnostics. Never send raw errors or call arguments."""
import functools
import hashlib
import inspect
import os
import re
import threading
import time

import config
import paths
import supabase_client as sb

_lock = threading.Lock()
_seen = {}
_slots = threading.BoundedSemaphore(2)


def shape(panel, action, message):
    text = str(message or '')[:20000]
    code = re.search(r'\b(?:PGRST\d{3}|HTTP\s+[45]\d\d|[A-Za-z]+Error)\b', text)
    tables = re.findall(r'\bcrm_pipeline_(?:boards|lanes|cards|activity)\b', text)
    error_code = code.group(0).replace(' ', '_') if code else 'unclassified'
    if 'reference is linked to multiple jobs' in text.lower():
        error_code = 'reference_multiple_jobs'
    return {'panel': panel if re.fullmatch(r'[a-z_]{1,60}', str(panel)) else 'unknown',
            'action': action if re.fullmatch(r'[a-z_]{1,100}', str(action)) else 'unknown',
            'code': error_code,
            'table_name': tables[0] if tables else '',
            'cached': '(cached)' in text,
            'app_version': paths.VERSION,
            'channel': 'dev' if os.environ.get('LINGUAR_DEV_MODE') == '1' else 'main',
            'fingerprint': hashlib.sha256(text.encode()).hexdigest()}


def report(panel, action, message):
    try:
        user = (sb.current_user() or {}).get('id')
        if not user: return False
        payload = shape(panel, action, message)
        payload['department'] = config.active_department()
        key = (user, payload['department'], panel, action, payload['fingerprint'])
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
        try:
            result = method(*args, **kwargs)
        except Exception as error:
            report(panel, action, error)
            raise
        if isinstance(result, dict) and result.get('ok') is False and result.get('error'):
            report(panel, action, result['error'])
        return result
    # pywebview strips the first parameter even for functions attached to
    # an instance; preserve the original bound-method introspection shape.
    signature = inspect.signature(method)
    call.__signature__ = signature.replace(parameters=[
        inspect.Parameter('self', inspect.Parameter.POSITIONAL_ONLY),
        *signature.parameters.values()])
    return call
