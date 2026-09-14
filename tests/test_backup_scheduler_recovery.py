"""An overlapping manual backup must not end the hourly backup chain."""
import data_backup as db


def test_busy_hourly_check_still_schedules_next_check(monkeypatch):
    scheduled = []
    monkeypatch.setattr(db, "_IN_PROGRESS", True)
    monkeypatch.setattr(db, "_NEXT_TIMER", None)
    monkeypatch.setattr(db, "_schedule_next", lambda: scheduled.append(True))
    worker = db.start_background()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert db._IN_PROGRESS is True  # The other worker still owns the lock.
    assert scheduled, "Busy check lost the next timer; backups eventually go stale"


def test_hourly_callback_recovers_after_manual_backup_finishes(monkeypatch):
    workers, timers, copies = [], [], []
    real_start = db.start_background

    def start():
        workers.append(real_start())

    class Timer:
        def __init__(self, interval, callback):
            self.callback = callback
            self.alive = False
            timers.append(self)

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(db.threading, "Timer", Timer)
    monkeypatch.setattr(db, "start_background", start)
    monkeypatch.setattr(db, "_NEXT_TIMER", None)
    monkeypatch.setattr(db, "_IN_PROGRESS", True)
    monkeypatch.setattr(db, "_LAST_REPORT", None)
    monkeypatch.setattr(db, "run_once", lambda **kw: copies.append(True) or {})
    db._scheduled_run()
    workers[-1].join(timeout=2)
    assert len(timers) == 1
    assert not copies  # No overlapping writer.
    db._IN_PROGRESS = False  # Manual worker completes.
    timers[0].alive = False
    timers[0].callback()
    workers[-1].join(timeout=2)
    assert copies == [True]
    assert len(timers) == 2  # Future checks continue too.


def test_busy_force_run_remains_one_shot(monkeypatch):
    scheduled = []
    monkeypatch.setattr(db, "_IN_PROGRESS", True)
    monkeypatch.setattr(db, "_schedule_next", lambda: scheduled.append(True))
    worker = db.start_background(force=True)
    worker.join(timeout=2)
    assert not scheduled
    assert db._IN_PROGRESS is True


def test_sqlite_sidecars_are_not_reported_as_verified_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "backup_dir", lambda: str(tmp_path))
    for suffix in ("", "-wal", "-shm"):
        (tmp_path / ("ems_jobs.db.20260914-075319" + suffix)).touch()
    assert [r["stamp"] for r in db.list_backups()] == ["20260914-075319"]
