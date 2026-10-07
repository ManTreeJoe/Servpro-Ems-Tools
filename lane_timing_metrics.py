"""Derived elapsed-time metrics over verified, chronological placement periods.

No writes, name-based person matching, last-activity ages or inferred timestamps.
"""


def summarize(periods, current, now, *, snapshot_id, estimator_ids, est_board,
              logs_board, parse):
    snapshot_cycles, arrivals, waiting = [], [], {}
    snapshot = None
    previous_board = None
    for period in periods:
        board, lane = period['board_id'], period['lane_id']
        if board == est_board and lane == snapshot_id and snapshot is None:
            snapshot = period
        if snapshot and board == est_board and lane in estimator_ids:
            snapshot_cycles.append(dict(started=snapshot['entered'],
                ended=period['entered'], assigned_lane=period['lane'],
                seconds=(parse(period['entered']) - parse(snapshot['entered'])).total_seconds()))
            snapshot = None
        if board == logs_board and previous_board != logs_board:
            arrivals.append(dict(entered=period['entered'], lane=period['lane']))
            if snapshot:
                # A later reopened estimator cycle must not falsely complete
                # a Snapshot cycle that already reached Logs without assignment.
                snapshot_cycles.append(dict(started=snapshot['entered'], ended=None,
                                            assigned_lane=None, seconds=None))
                snapshot = None
        previous_board = board
        name = period['lane'].upper().strip()
        # These labels classify recorded intervals only; they never create
        # event timestamps. Keep distinct lanes and boards separate.
        if name.startswith(('TBS ', 'PENDING APPROVAL')) or name in (
                'ON HOLD', 'TEST/CLEARANCE', 'TEST / CLEARANCE'):
            key = (board, lane)
            item = waiting.setdefault(key, dict(board=period['board'], lane=period['lane'],
                seconds=0, visits=0, unknown_visits=0))
            item['visits'] += 1
            if period['seconds'] is None:
                item['unknown_visits'] += 1
            else:
                item['seconds'] += period['seconds']
    if snapshot:
        running = bool(periods and periods[-1]['current'] and
                       current.get('idBoard') == est_board and
                       current.get('idList') == snapshot_id)
        snapshot_cycles.append(dict(started=snapshot['entered'], ended=None,
            assigned_lane=None, seconds=(now-parse(snapshot['entered'])).total_seconds()
            if running else None))
    # Board tenure spans internal Logs lane changes. Require a verified final
    # placement match before extending the most recent arrival up to now.
    logs_age = None
    if arrivals and periods and periods[-1]['current'] and current.get('idBoard') == logs_board:
        logs_age = (now-parse(arrivals[-1]['entered'])).total_seconds()
    return dict(snapshot_cycles=snapshot_cycles, waiting_lanes=list(waiting.values()),
                logs_arrivals=arrivals, logs_age_seconds=logs_age)
