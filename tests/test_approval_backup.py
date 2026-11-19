import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    'approval_rehearsal', Path(__file__).resolve().parents[1] / 'deploy/employee-access/server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_backup_never_waits_for_password_or_stdin(monkeypatch, tmp_path, capsys):
    process = Mock()
    process.wait.return_value = 0
    launch = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    query = Mock()
    module.backup('verified-main-db', tmp_path, query)
    args = launch.call_args.args[0]
    assert '--no-password' in args
    assert '--lock-wait-timeout=30s' in args
    assert '-i' not in args
    assert launch.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert 'Recovery backup completed' in capsys.readouterr().out
    query.assert_not_called()


def test_backup_timeout_stops_only_its_own_named_session(monkeypatch, tmp_path, capsys):
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired('docker', 15), 0]
    process.poll.return_value = None
    monkeypatch.setattr(module.subprocess, 'Popen', Mock(return_value=process))
    clock = iter([0, 601])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(module.uuid, 'uuid4', lambda: Mock(hex='a' * 32))
    query = Mock()
    with pytest.raises(RuntimeError, match='Migration was not started'):
        module.backup('verified-main-db', tmp_path, query)
    sql = query.call_args.args[0]
    assert "application_name='oneloss_approval_backup_" + 'a' * 32 + "'" in sql
    assert "usename='supabase_admin'" in sql
    assert '601s' in capsys.readouterr().out
    process.terminate.assert_called_once()


def test_cancel_keeps_partial_files_and_cleans_own_backup(monkeypatch, tmp_path):
    process = Mock()
    process.wait.side_effect = [KeyboardInterrupt, 0]
    process.poll.return_value = None
    monkeypatch.setattr(module.subprocess, 'Popen', Mock(return_value=process))
    query = Mock()
    with pytest.raises(RuntimeError, match='cancelled before migration'):
        module.backup('verified-main-db', tmp_path, query)
    assert (tmp_path / 'database.dump').exists()
    query.assert_called_once()
    process.terminate.assert_called_once()
