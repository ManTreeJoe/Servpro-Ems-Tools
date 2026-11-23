"""One-time Main-only move from the retired hosted project to the VM.

No company data, passwords or provider credentials are logged or shipped here.
The caller skips this module entirely for Trial/Dev. Custom endpoints stay put.
"""
import datetime
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

OLD_URL = 'https://oqwwapqnzzhefqxobadl.supabase.co'
SERVER_URL = 'https://api.oneloss.work'
PUBLIC_KEY = 'sb_publishable_jhW_P8jFtwZ_LgJcbh2xea_aAvuSKrw'


def migrate(config_path):
    path = Path(config_path)
    if not path.is_file():
        return False
    original = path.read_bytes()
    config = json.loads(original.decode('utf-8-sig'))
    url = str(config.get('supabase_url') or '').rstrip('/') if isinstance(config, dict) else ''
    if url not in (OLD_URL, SERVER_URL):
        return False
    moving = url == OLD_URL
    # The endpoint records whether this move is needed. The posting pause is
    # an independent operator choice, not a migration-completion marker.
    # Existing server profiles must keep their tokens and session unchanged.
    if not moving:
        return False
    for dept in (config.get('departments') or {}).values():
        if isinstance(dept, dict) and dept.get('supabase_url') and str(dept['supabase_url']).rstrip('/') not in (OLD_URL, SERVER_URL):
            raise RuntimeError('Custom franchise connection requires a reviewed migration.')
    backup = Path(tempfile.mkdtemp(prefix='before-server-switch-', dir=path.parent))
    if os.name == 'nt':
        # Use the actual SID; never interpolate an untrusted name into a shell.
        sid_result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, check=True, creationflags=0x08000000)
        import csv
        sid = next(csv.reader([sid_result.stdout.strip()]))[1]
        subprocess.run(['icacls', str(backup), '/inheritance:r', '/grant:r', '*' + sid + ':(OI)(CI)F'], capture_output=True, check=True, creationflags=0x08000000)
    else:
        backup.chmod(0o700)
    (backup / 'config.json').write_bytes(original)
    session = path.parent / 'supabase_session.json'
    if session.is_file():
        shutil.copy2(session, backup / session.name)

    def rewrite(value):
        if isinstance(value, dict):
            for key in list(value):
                if key == 'trello_token':
                    value[key] = ''
                elif key == 'supabase_url' and str(value[key] or '').rstrip('/') == OLD_URL:
                    value[key] = SERVER_URL
                elif key == 'supabase_anon_key' and value[key]:
                    value[key] = PUBLIC_KEY
                else:
                    rewrite(value[key])
        elif isinstance(value, list):
            for item in value:
                rewrite(item)
    rewrite(config)
    config['supabase_url'] = SERVER_URL
    config['supabase_anon_key'] = PUBLIC_KEY
    config['trello_writes_paused'] = True
    temp = path.with_name('config.server-migration.tmp')
    try:
        temp.write_text(json.dumps(config, indent=2), encoding='utf-8')
        if moving:
            session.unlink(missing_ok=True)
        os.replace(temp, path)
    except Exception:
        path.write_bytes(original)
        if (backup / session.name).is_file():
            shutil.copy2(backup / session.name, session)
        raise
    finally:
        temp.unlink(missing_ok=True)
    return True
