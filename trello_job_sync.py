"""Walk Trello once and describe the jobs it found.

Reading the boards is the same work whichever database is going to store
the result — it is Trello I/O, not storage. Keeping it here means the two
backends can differ in HOW they write (row at a time locally, in bulk
against a hosted one) without drifting on WHAT a card means: which cards
count, how a lane is resolved, where the claim number and carrier live.

`ems_db_sqlite.sync_from_trello` and `ems_db_supabase.sync_from_trello`
both start from `collect()`.
"""
from __future__ import annotations

from typing import Iterable


def _card_columns(tc, card) -> dict:
    """{column: value} for every card field that has a column.

    Driven by `job_settings` — FIELDS says where a value lives on the
    card, COLUMN_FIELDS says which column it belongs in. Using that table
    rather than a hand-picked list is the point: the job-info editor
    already writes these fields back to the card, so a sync reading a
    different set would quietly disagree with the editor.

    Blank values are dropped, not stored: `upsert_job` treats a blank as
    "don't overwrite", and passing one explicitly would just be noise.
    Carriers are canonicalised here for the same reason they are on the
    editor's way in.
    """
    try:
        import job_settings as _js
    except Exception:
        return {}
    try:
        fields = tc.parse_card_desc((card or {}).get("desc") or "") or {}
    except Exception:
        return {}
    out = {}
    for entry in getattr(_js, "FIELDS", ()):
        # (field_id, section, key, label, core)
        fid, section, key = entry[0], entry[1], entry[2]
        col = (getattr(_js, "COLUMN_FIELDS", {}) or {}).get(fid)
        if not col:
            continue                     # lives in the JSON blob, not a column
        val = ((fields.get(section) or {}).get(key) or "").strip()
        if not val:
            continue
        if col == "carrier":
            try:
                import carriers as _carriers
                val = _carriers.normalize(val) or val
            except Exception:
                pass
        out[col] = val
    return out


def resolve_against_existing(records, exists) -> dict:
    """Point cards at the job they already belong to, under whichever
    spelling the index happens to hold.

    A card titled "Knudsen, Seth - Mercury" keys to `knudsen, seth`; the
    run doc and the folder call him "Seth Knudsen", keying to
    `seth knudsen`. Writing the card's key makes a SECOND job for one
    person, and the audit keeps reading the first — which is how a job
    ends up with the carrier on a row nothing looks at. Measured on live
    data: a full sync would have done this to nine open jobs.

    `exists(key)` answers whether a job row already exists. Records are
    mutated in place: `canon_key` becomes the surviving identity and the
    card's own spelling is added to `aliases`, so a search for it still
    finds the job.

    Only ever redirects INTO a row that already exists. It never merges
    two existing jobs — that needs a person, and the 🧩 Name issues
    review is where it happens.

    Returns {"redirected": n, "pairs": [(card_key, existing_key)]}.
    """
    try:
        from job_name_issues import swapped_name
        from ems_db_sqlite import canon_key
    except Exception:                                  # pragma: no cover
        return {"redirected": 0, "pairs": []}

    out = {"redirected": 0, "pairs": []}
    for rec in records or ():
        key = rec.get("canon_key") or ""
        if not key or exists(key):
            continue                       # already the right identity
        sw = swapped_name(rec.get("display_name") or "")
        if not sw:
            continue
        other = canon_key(sw)
        if not other or other == key or not exists(other):
            continue
        # The card's spelling stays searchable; the job keeps the key the
        # rest of the system already uses.
        aliases = list(rec.get("aliases") or [])
        aliases.append(rec.get("display_name") or "")
        rec["aliases"] = aliases
        rec["canon_key"] = other
        out["redirected"] += 1
        out["pairs"].append((key, other))
    return out


class CardRecord(dict):
    """One open Trello card, in the shape a job index wants.

    Plain dict so it crosses the pywebview bridge and JSON without a
    converter; a class only for the name in tracebacks.
    """


def collect(*, exclude_quality: bool = True,
            exclude_logs: bool = True,
            lane_filter: Iterable[str] | None = None,
            progress_cb=None) -> dict:
    """Read every in-scope board and return what the cards say.

    Returns ``{"boards": int, "records": [CardRecord, ...]}`` where each
    record carries: canon_key, display_name, claim_number, carrier,
    status, board, lane, card_id.

    `exclude_quality` skips AR / billing-dispute boards. `exclude_logs`
    skips the LOGS - EMS board (closed jobs) — the canonical question of
    this index is "what's open". `lane_filter` restricts to named lanes
    for a cheap targeted refresh.

    `progress_cb(done, total, card_name)` is called per card if given.

    Never raises for one bad board or card: a board whose lists or cards
    can't be read contributes nothing and the rest still sync. A sync
    that aborts on the first hiccup leaves the index half-refreshed with
    no sign of which half.
    """
    import trello_client as tc
    from ems_db_sqlite import canon_key

    boards = tc.list_boards(exclude_quality=exclude_quality)

    # Resolve closed-board ids once so the per-board loop can stamp
    # status='closed' without a second Trello call.
    closed_board_ids: set[str] = set()
    try:
        if exclude_logs:
            logs_bid = tc.get_logs_board_id()
            if logs_bid:
                closed_board_ids.add(logs_bid)
                # Drop them from the walk too — saves the /cards call
                # when the caller doesn't want them.
                boards = [b for b in boards
                          if b.get("id") not in closed_board_ids]
    except Exception:
        pass

    records: list[CardRecord] = []
    for b in boards:
        bid = b.get("id")
        if not bid:
            continue
        try:
            lists = tc._call(f"/boards/{bid}/lists",
                             params={"fields": "id,name"}) or []
        except Exception:
            lists = []
        list_name_by_id = {l["id"]: l.get("name", "")
                           for l in lists if l.get("id")}
        try:
            cards = tc._call(f"/boards/{bid}/cards",
                             params={"fields":
                                     "id,name,shortUrl,idList,closed,desc"}) or []
        except Exception:
            cards = []

        for ci, card in enumerate(cards, start=1):
            if card.get("closed"):
                continue
            lane = list_name_by_id.get(card.get("idList", ""), "")
            if lane_filter is not None and lane not in lane_filter:
                continue
            name = (card.get("name") or "").strip()
            if not name:
                continue
            key = canon_key(name)
            if not key:
                continue
            # Claim number and carrier ride along in the desc we already
            # fetched, so reading them costs nothing extra.
            # Everything the card states about the job, not just two
            # fields. `job_settings` already maps every card field to its
            # column and round-trips them in the job-info editor; reading
            # the same table here means the sync and the editor cannot
            # disagree about where a value lives.
            #
            # This used to take CLAIM NUMBER and INSURANCE COMPANY and
            # discard the rest, which is why a card with an address,
            # phone, adjuster, agent, year built and date of loss sat
            # beside a job row that was completely empty.
            cols = _card_columns(tc, card)
            claim = cols.get("claim_number", "")
            carrier = cols.get("carrier", "")

            records.append(CardRecord({
                "canon_key":    key,
                "display_name": name,
                "claim_number": claim,
                "carrier":      carrier,
                "status":       ("closed" if bid in closed_board_ids
                                 else "active"),
                "board":        b.get("name", ""),
                "lane":         lane,
                "card_id":      card.get("id") or "",
                # Every column the card stated. claim_number and carrier
                # stay as their own keys for the callers that only want
                # those two; `columns` is the whole set.
                "columns":      cols,
            }))
            if progress_cb is not None:
                try:
                    progress_cb(ci, len(cards), name)
                except Exception:
                    pass

    return {"boards": len(boards), "records": records}
