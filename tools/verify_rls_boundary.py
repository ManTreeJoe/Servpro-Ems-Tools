"""Verify the signed-out Supabase boundary without printing credentials/data."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1]))

import config


def _status(url: str, key: str, *, method: str = "GET") -> int:
    request = Request(
        url,
        data=b"{}" if method == "POST" else None,
        method=method,
        headers={"apikey": key, "content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status
    except HTTPError as error:
        return error.code


def main() -> None:
    settings = config.load()
    base = str(settings.get("supabase_url") or "").rstrip("/")
    key = str(settings.get("supabase_anon_key") or "")
    if not base or not key:
        raise SystemExit("Supabase is not configured")

    statuses = {
        "jobs_without_login": _status(
            f"{base}/rest/v1/jobs?select=canon_key&limit=1", key
        ),
        "identity_rpc_without_login": _status(
            f"{base}/rest/v1/rpc/my_departments", key, method="POST"
        ),
    }
    print(json.dumps(statuses))
    # 404/500 do not prove RLS; they can mean the endpoint or migration is
    # broken. Only an explicit authentication/authorization denial passes.
    if any(status not in (401, 403) for status in statuses.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
