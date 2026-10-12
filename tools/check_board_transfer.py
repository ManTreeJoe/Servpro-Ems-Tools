"""Read-only signed-in transfer check. Prints sizes/counts, never card content."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import supabase_client as sb
import pipeline_web as pipeline
import mirror_board_transfer as transfer

rpc = sb.rpc
events = []

def measured(name, data):
    if name != 'hub_trello_boards':
        raise RuntimeError('Unexpected RPC in read-only transfer check')
    result = rpc(name, data)
    events.append({'json_bytes': len(json.dumps(result).encode('utf-8')),
                   'boards': len(result.get('boards', [])),
                   'unchanged': sum(b.get('unchanged') is True for b in result.get('boards', []))})
    return result

sb.rpc = measured
transfer.clear()
for iteration in range(2):
    result = pipeline._server_board_payload()
    print(json.dumps({'read': iteration + 1, 'usable': bool(result and result.get('ok')),
                      'transfer': events[-1] if events else None}), flush=True)
assert len(events) == 2 and events[1]['unchanged'] == events[1]['boards'] > 0
assert events[1]['json_bytes'] < events[0]['json_bytes'] / 10
