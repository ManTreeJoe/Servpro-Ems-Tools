"""Keep a known-good installer, and be able to prove it is still good.

The update path is one-way: `version.txt` names the newest build and
every PC follows it on next launch. That is fine until the newest build
is the problem, at which point there is nowhere to go back TO -- the
previous installer only exists on whichever machine happened to build
it.

So each release that is confirmed working gets copied somewhere everyone
can reach, with its SHA-256 recorded. The hash is the point. A file
sitting on a share is only a rollback if it is still the file you put
there; without a hash, "we have a known-good installer" is a belief, and
you find out it was wrong on the day you need it.

Nothing here publishes on its own. Every write takes an explicit
destination, because copying an installer to a share is how other people
end up installing it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil

MANIFEST = "known-good.json"
KEEP = 3          # how many previous releases stay on the share


def sha256(path: str, _chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_chunk), b""):
            h.update(block)
    return h.hexdigest()


def _manifest_path(root: str) -> str:
    return os.path.join(root, MANIFEST)


def read_manifest(root: str) -> dict:
    try:
        with open(_manifest_path(root), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {"releases": []}


def record(installer: str, root: str, version: str, *,
           notes: str = "", when: str = "") -> dict:
    """Copy `installer` under `root/<version>/` and record its hash.

    `when` is passed in rather than read from the clock so a caller can
    stamp it consistently and so this is testable.
    """
    if not os.path.isfile(installer):
        return {"ok": False, "error": f"no such installer: {installer}"}
    if not version:
        return {"ok": False, "error": "version is required"}

    digest = sha256(installer)
    dest_dir = os.path.join(root, version)
    dest = os.path.join(dest_dir, os.path.basename(installer))
    try:
        os.makedirs(dest_dir, exist_ok=True)
        # Copy to a temp name and rename, so an interrupted copy cannot
        # leave a half-written file that looks like a valid rollback.
        tmp = dest + ".part"
        shutil.copyfile(installer, tmp)
        if sha256(tmp) != digest:
            os.remove(tmp)
            return {"ok": False, "error": "copy did not match the source"}
        os.replace(tmp, dest)
    except OSError as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    man = read_manifest(root)
    rel = [r for r in man.get("releases", []) if r.get("version") != version]
    rel.insert(0, {
        "version": version,
        "file": os.path.basename(installer),
        "path": dest,
        "sha256": digest,
        "bytes": os.path.getsize(dest),
        "recorded": when or _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": notes,
    })
    dropped = rel[KEEP:]
    man["releases"] = rel[:KEEP]
    man["current"] = version
    try:
        with open(_manifest_path(root), "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=2)
    except OSError as ex:
        return {"ok": False, "error": f"manifest: {ex}"}

    # Prune only AFTER the manifest is safely written: losing the record
    # of what was kept is worse than leaving an extra folder behind.
    for old in dropped:
        try:
            shutil.rmtree(os.path.join(root, old.get("version", "")),
                          ignore_errors=True)
        except OSError:
            pass
    return {"ok": True, "version": version, "path": dest,
            "sha256": digest, "pruned": [d.get("version") for d in dropped]}


def verify(root: str) -> dict:
    """Re-hash every kept installer. This is the whole reason the hash
    is recorded, so it is a real check, not a file-exists test."""
    man = read_manifest(root)
    good, bad = [], []
    for rel in man.get("releases", []):
        p = rel.get("path") or ""
        if not os.path.isfile(p):
            bad.append({**rel, "problem": "missing"})
            continue
        if sha256(p) != rel.get("sha256"):
            bad.append({**rel, "problem": "hash does not match"})
            continue
        good.append(rel)
    return {"ok": not bad, "good": good, "bad": bad,
            "current": man.get("current", "")}


def rollback_target(root: str, *, before: str = "") -> dict:
    """The newest kept release older than `before` (default: the current
    one). Returns the path to run -- it never installs anything, because
    that is a decision someone makes at a machine, not a script."""
    man = read_manifest(root)
    rel = man.get("releases", [])
    before = before or man.get("current", "")
    for r in rel:
        if r.get("version") != before:
            if os.path.isfile(r.get("path") or ""):
                return {"ok": True, **r}
            return {"ok": False, "error": f"kept copy missing: {r.get('path')}"}
    return {"ok": False, "error": "no earlier release is kept"}
