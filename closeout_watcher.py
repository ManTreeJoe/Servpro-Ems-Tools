"""Closeout / snapshot-ready card detection.

The Snapshot tool already knows how to pre-fill itself from a Trello card
(`snapshot_gui._open_snapshot_picker` + `_fill_from_trello_card`). This
module adds the *discovery* half: which cards SHOULD have a snapshot
drafted right now?

Two signals contribute:

1. The card sits in the configured snapshot-ready lane
   (`config["trello_snapshot_list_id"]`).
2. A recent comment on any in-scope card matches a closeout marker
   ("ready for Snapshot", "closed and ready", etc.) — catches cases where
   a tech wrote the magic phrase but nobody has moved the card to the
   SNAPSHOT lane yet.

Cards previously drafted (tracked in persistence under
`closeout_drafted`) are filtered out so the same card doesn't keep
showing up after the user generated its snapshot. The dismissal helpers
in persistence handle "I'll deal with this later" without permanently
hiding the card.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import config
import persistence as per
import trello_client as tc


# Comment patterns that signal a job is closeout-ready. The "- Auto"
# suffix is left off the regex so manual posts ("This is ready for
# Snapshot") match too. Order doesn't matter; first hit wins.
_CLOSEOUT_COMMENT_RE = re.compile(
    r"(?:ready (?:for|to) snapshot|closed and ready|"
    r"snapshot ready|please snapshot|close and snapshot)",
    re.IGNORECASE,
)

# How far back to scan a card's action stream looking for a closeout
# marker. Trello includes the last 50 actions per card via get_card,
# which usually covers a few weeks of activity for typical jobs.
_COMMENT_LOOKBACK_DAYS = 30


def _utcnow() -> _dt.datetime:
    # Naive UTC — see note in trello_hygiene._utcnow.
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _parse_iso(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.split(".")[0].rstrip("Z"))
    except (ValueError, AttributeError):
        return None


def _matching_comment(card: dict[str, Any], *,
                      since: _dt.datetime
                      ) -> dict[str, Any] | None:
    """Return the most-recent commentCard action whose body matches the
    closeout regex AND was posted at or after `since`. None when no such
    comment exists in the inline action window."""
    for a in card.get("actions") or []:
        if a.get("type") != "commentCard":
            continue
        c_dt = _parse_iso(a.get("date") or "")
        if c_dt is None or c_dt < since:
            continue
        text = ((a.get("data") or {}).get("text") or "")
        if _CLOSEOUT_COMMENT_RE.search(text):
            return a
    return None


def _candidate_card(card: dict[str, Any], *, source: str,
                    trigger_iso: str = "",
                    trigger_text: str = "",
                    lane_name: str = "") -> dict[str, Any]:
    """Format a single closeout candidate so the GUI / digest can render
    a homogeneous list regardless of which signal surfaced the card."""
    return {
        "card_id":      card.get("id", ""),
        "card_name":    card.get("name", "(unnamed)"),
        "card_url":     card.get("shortUrl", ""),
        "board_id":     card.get("idBoard", ""),
        "list_id":      card.get("idList", ""),
        "lane":         lane_name,
        "source":       source,                 # "lane" | "comment"
        "trigger_iso":  trigger_iso,
        "trigger_text": (trigger_text or "")[:240],
    }


def find_lane_candidates() -> list[dict[str, Any]]:
    """Cards currently sitting in the configured SNAPSHOT lane. Empty
    list when the lane id isn't configured or the lane is empty."""
    cfg = config.load()
    list_id = (cfg.get("trello_snapshot_list_id") or "").strip()
    if not list_id:
        return []
    try:
        cards = tc.cards_in_list(list_id) or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for c in cards:
        lane = tc.get_lane_name(c.get("idBoard"), c.get("idList"))
        out.append(_candidate_card(
            c, source="lane", lane_name=lane))
    return out


def find_comment_candidates(*, lookback_days: int = _COMMENT_LOOKBACK_DAYS,
                             max_per_board: int = 200,
                             progress_cb=None) -> list[dict[str, Any]]:
    """Walk every in-scope board, find cards whose most recent matching
    comment fired within `lookback_days`. One get_card per active
    candidate — boards with no activity are skipped via the lightweight
    cards_in_list shape first."""
    since = _utcnow() - _dt.timedelta(days=lookback_days)
    # AR / billing boards excluded — closeout-ready comments don't apply
    # to billing follow-up cards. Centralised filter; see
    # trello_client.QUALITY_EXCLUDED_BOARD_NAMES.
    boards = tc.list_boards(exclude_quality=True) or []
    out: list[dict[str, Any]] = []

    # Two-pass: cheap enumeration first (just need card ids), then
    # full get_card on cards whose dateLastActivity is recent enough
    # that a closeout comment is even possible.
    targets: list[tuple[dict[str, Any], str, str]] = []
    for b in boards:
        try:
            lists = tc._call(
                f"/boards/{b['id']}/lists",
                params={"fields": "id,name", "filter": "open"},
            ) or []
        except Exception:
            continue
        for lst in lists:
            try:
                cards = tc.cards_in_list(
                    lst.get("id"),
                    fields="id,name,shortUrl,idBoard,idList,closed,"
                            "dateLastActivity",
                ) or []
            except Exception:
                continue
            for c in cards[:max_per_board]:
                last_iso = c.get("dateLastActivity") or ""
                last_dt = _parse_iso(last_iso)
                if last_dt is None or last_dt < since:
                    continue
                targets.append((c, b.get("name", ""), lst.get("name", "")))

    total = len(targets)
    for i, (summary, board_name, lane_name) in enumerate(targets, start=1):
        cid = summary.get("id")
        if not cid:
            continue
        try:
            card = tc.get_card(cid, actions_limit=50)
        except Exception:
            card = None
        if card is None:
            continue
        match = _matching_comment(card, since=since)
        if match is None:
            continue
        out.append(_candidate_card(
            card, source="comment",
            trigger_iso=match.get("date") or "",
            trigger_text=((match.get("data") or {}).get("text") or ""),
            lane_name=lane_name,
        ))
        if progress_cb is not None:
            try:
                progress_cb(i, total, card.get("name", ""))
            except Exception:
                pass
    return out


def _existing_snapshot_pdf_names() -> set[str]:
    """Return the canonicalized basenames of every snapshot PDF
    currently on disk. Used to skip cards whose snapshot was already
    generated outside (or before) the drafted-flag was wired — without
    this, legacy jobs that have a PDF but no `closeout_drafted` entry
    keep getting flagged as "ready for snapshot."

    Canonicalization: lowercase, strip the ".pdf" extension, drop any
    " snapshot" suffix the trello-comment pdf name appends. Returns a
    set of stripped insured-style names — caller compares against
    card_name via the same _canon_pdf_key function below."""
    import os as _os
    try:
        import config as _cfg
        out_dir = (_cfg.load().get("snapshot_output") or "").strip()
    except Exception:
        out_dir = ""
    if not out_dir or not _os.path.isdir(out_dir):
        return set()
    keys: set[str] = set()
    try:
        with _os.scandir(out_dir) as it:
            for e in it:
                if not e.is_file():
                    continue
                name = e.name
                if not name.lower().endswith(".pdf"):
                    continue
                keys.add(_canon_pdf_key(name[:-4]))
    except OSError:
        return set()
    return {k for k in keys if k}


def _canon_pdf_key(s: str) -> str:
    """Lowercase + alphanum-only + collapse whitespace. Used to fuzzy-
    match a Trello card_name against an on-disk snapshot PDF basename,
    so " - State Farm" / "(Contents)" / "Snapshot" suffix differences
    don't prevent the match."""
    import re as _re
    s = (s or "").lower()
    # Drop common PDF-name suffixes the snapshot tool appends.
    s = _re.sub(r"\bsnapshot\b", " ", s)
    # Drop parentheticals like "(Contents)" / "(Self Pay)" — these are
    # job variants, not part of the insured name on the snapshot PDF.
    s = _re.sub(r"\([^)]*\)", " ", s)
    # Drop carrier-suffix tail (anything after " - <carrier>").
    s = s.split(" - ", 1)[0]
    s = _re.sub(r"[^a-z0-9]+", " ", s).strip()
    return " ".join(s.split())


def find_snapshot_candidates(*, include_lane: bool = True,
                              include_comments: bool = True,
                              skip_drafted: bool = True,
                              skip_existing_pdf: bool = True,
                              lookback_days: int = _COMMENT_LOOKBACK_DAYS,
                              progress_cb=None) -> list[dict[str, Any]]:
    """Combined scan. Lane-based candidates are listed first (cheapest +
    most authoritative); comment-based candidates fill in the rest. Cards
    surfaced by both signals appear once with `source="lane"` since the
    lane signal is stronger.

    `skip_existing_pdf` filters out cards whose canonicalized card_name
    matches a PDF already on disk in snapshot_output. This catches
    legacy jobs whose snapshot was generated before mark_drafted was
    wired into the snapshot-success path — without this, the Hygiene
    list keeps surfacing already-snapshotted cards forever."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    if include_lane:
        for c in find_lane_candidates():
            cid = c["card_id"]
            if cid and cid not in seen:
                seen.add(cid)
                out.append(c)

    if include_comments:
        for c in find_comment_candidates(
                lookback_days=lookback_days,
                progress_cb=progress_cb):
            cid = c["card_id"]
            if cid and cid not in seen:
                seen.add(cid)
                out.append(c)

    if skip_drafted:
        drafted = per.get("closeout_drafted") or {}
        out = [c for c in out if c["card_id"] not in drafted]

    if skip_existing_pdf:
        pdf_keys = _existing_snapshot_pdf_names()
        if pdf_keys:
            out = [c for c in out
                   if _canon_pdf_key(c.get("card_name", "")) not in pdf_keys]

    return out


# ── Drafted-card tracking ─────────────────────────────────────────────────
# Used by the GUI when the user opens the Snapshot tool for a candidate;
# also reusable from any other entry point that converts a "ready"
# candidate into an actual draft so the watcher stops surfacing it.

def mark_drafted(card_id: str) -> None:
    """Record that a snapshot has been drafted for `card_id`. Stamped
    with current Unix time so we could later expire the flag if the
    user wants to re-draft (not currently exposed)."""
    if not card_id:
        return
    drafted = per.get("closeout_drafted") or {}
    if not isinstance(drafted, dict):
        drafted = {}
    drafted[card_id] = _utcnow().isoformat(timespec="seconds")
    per.set_value("closeout_drafted", drafted)


def clear_drafted(card_id: str) -> None:
    """Remove the drafted flag for `card_id` (re-surface in next scan)."""
    if not card_id:
        return
    drafted = per.get("closeout_drafted") or {}
    if isinstance(drafted, dict) and card_id in drafted:
        drafted.pop(card_id, None)
        per.set_value("closeout_drafted", drafted)


# ── CLI smoke test ────────────────────────────────────────────────────────

def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python closeout_watcher.py scan [--no-comments] [--no-skip]")
        print("  python closeout_watcher.py mark <card_id>")
        print("  python closeout_watcher.py clear <card_id>")
        return 1
    cmd = argv[0]
    if cmd == "scan":
        include_comments = "--no-comments" not in argv
        skip_drafted = "--no-skip" not in argv

        def _progress(done, total, name):
            print(f"  [{done}/{total}] {name[:60]}")

        cands = find_snapshot_candidates(
            include_comments=include_comments,
            skip_drafted=skip_drafted,
            progress_cb=_progress)
        print()
        if not cands:
            print("✓ No closeout candidates.")
            return 0
        for c in cands:
            tag = c["source"].upper()
            print(f"[{tag}]  [{c['lane']}]  {c['card_name']}")
            print(f"  {c['card_url']}")
            if c["trigger_text"]:
                print(f"  ↳ {c['trigger_text'][:100]}")
            print()
        print(f"{len(cands)} candidate(s).")
        return 0
    if cmd == "mark":
        if len(argv) < 2:
            print("Usage: python closeout_watcher.py mark <card_id>")
            return 1
        mark_drafted(argv[1])
        print(f"Marked drafted: {argv[1]}")
        return 0
    if cmd == "clear":
        if len(argv) < 2:
            print("Usage: python closeout_watcher.py clear <card_id>")
            return 1
        clear_drafted(argv[1])
        print(f"Cleared drafted flag: {argv[1]}")
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
