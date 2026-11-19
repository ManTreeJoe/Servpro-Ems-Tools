"""Verify the operator rehearsal cannot export or commit the database."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "approval_rehearsal", Path(__file__).resolve().parents[1] / "deploy/employee-access/server.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def rehearsal(monkeypatch, tmp_path):
    sql = "begin;\ncreate schema example_only;\ncommit;\n"
    (tmp_path / "approval.sql").write_text(sql)
    (tmp_path / "approval.sha256").write_text(hashlib.sha256(sql.encode()).hexdigest())
    config = tmp_path / "compose.json"
    config.write_text(json.dumps({"name": module.PROJECT}))
    monkeypatch.setattr(module, "CONFIG", config)
    monkeypatch.setattr(module, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "server.py"))
    monkeypatch.setattr(module.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(module.os, "umask", lambda value: None)
    monkeypatch.setattr(module.sys, "argv", ["server.py", "rehearse"])
    commands = []
    def command(args, **kwargs):
        commands.append(args)
        if args[:2] == ["docker", "ps"]:
            output = "main-db"
        elif args[:2] == ["docker", "inspect"]:
            output = json.dumps([{"Config": {"Labels": {"com.docker.compose.project": module.PROJECT}}}])
        elif "pg_namespace" in kwargs.get("input", ""):
            output = "f"
        else:
            output = '{"jobs":2353,"users":8,"memberships":8,"admins":2}'
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")
    monkeypatch.setattr(module, "command", command)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    monkeypatch.setattr(module.subprocess, "run", run)
    return commands, run, tmp_path


def test_rehearsal_never_exports_and_always_submits_rollback(rehearsal, capsys):
    commands, run, root = rehearsal
    module.main()
    assert all("pg_dump" not in args and "pg_restore" not in args for args in commands)
    probe = run.call_args.kwargs["input"]
    assert probe.rstrip().endswith("rollback;")
    assert "commit;" not in probe.lower()
    assert "set local lock_timeout='3s'" in probe
    assert "set local transaction_timeout='60s'" in probe
    assert run.call_args.kwargs["timeout"] == 75
    assert not list(root.rglob("database.dump"))
    assert "NO database export" in capsys.readouterr().out
    assert len(list(root.rglob("rehearsal-pass.json"))) == 1


def test_failed_rehearsal_cannot_write_pass_marker(rehearsal):
    _, run, root = rehearsal
    run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="private error")
    with pytest.raises(RuntimeError, match="Rehearsal rolled back"):
        module.main()
    assert not list(root.rglob("rehearsal-pass.json"))
    assert len(list(root.rglob("rehearsal-private.log"))) == 1
