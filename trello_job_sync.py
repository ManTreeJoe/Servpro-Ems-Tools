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

import json
from typing import Iterable


def _card_values(card) -> dict:
    """Return every recognized nonblank Job Info value on a card."""
    try:
        import job_settings as _js
        values = _js.from_card((card or {}).get("desc") or "") or {}
        return {key: str(value).strip() for key, value in values.items()
                if str(value or "").strip()}
    except Exception:
        return {}


def _card_columns(tc, card, values=None) -> dict:
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
    values = values if isinstance(values, dict) else _card_values(card)
    out = {}
    for entry in getattr(_js, "FIELDS", ()):
        # (field_id, section, key, label, core)
        fid, section, key = entry[0], entry[1], entry[2]
        col = (getattr(_js, "COLUMN_FIELDS", {}) or {}).get(fid)
        if not col:
            continue                     # lives in the JSON blob, not a column
        val = str(values.get(fid) or "").strip()
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


def merge_card_metadata(existing: dict | None, record: dict) -> dict:
    """Merge light Trello text into metadata without erasing Hub edits.

    ``settings`` is the current Hub value and ``trello_base`` is the last
    value observed on the card.  A new card value advances the Hub value only
    when nobody changed that same field in Linguar Hub since the prior sync.
    """
    existing = existing or {}
    metadata = existing.get("metadata")
    if not isinstance(metadata, dict):
        raw = existing.get("metadata_json") or ""
        try:
            metadata = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            metadata = {}
    metadata = dict(metadata or {})
    saved = dict(metadata.get("settings") or {})
    prior_base = dict(metadata.get("trello_base") or {})
    incoming = dict(record.get("settings") or {})
    for field_id, value in incoming.items():
        current = str(saved.get(field_id) or "").strip()
        previous = str(prior_base.get(field_id) or "").strip()
        if not current or current == previous:
            saved[field_id] = value
    metadata.update({"board": record.get("board") or "",
                     "lane": record.get("lane") or ""})
    if saved:
        metadata["settings"] = saved
    if incoming:
        metadata["trello_base"] = incoming
    return metadata


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


def collapse_records(records: Iterable[dict]) -> list[CardRecord]:
    """Merge cards that resolve to one job without losing card links.

    Historical Logs cards often share a canonical name with a currently
    active card.  A job row needs one coherent view of those cards: older
    cards may fill fields the current card omits, but an active card must
    win current values, name, lane and status.  Callers still retain the
    original record list for writing every Trello-card link.
    """
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for rec in records:
        key = str(rec.get("canon_key") or "").strip()
        if not key:
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(rec)

    collapsed: list[CardRecord] = []
    for key in order:
        cards = grouped[key]
        active = [r for r in cards if r.get("status") == "active"]
        winner = (active or cards)[-1]
        merged = CardRecord(dict(winner))

        # Historical values establish the base; active cards override them.
        # Blank values never participate, matching the database partial-update
        # rule used by both backends.
        precedence = ([r for r in cards if r.get("status") != "active"] +
                      active)
        columns: dict[str, str] = {}
        settings: dict[str, str] = {}
        aliases: list[str] = []
        for rec in precedence:
            for field, value in (rec.get("columns") or {}).items():
                if str(value or "").strip():
                    columns[field] = value
            for field, value in (rec.get("settings") or {}).items():
                if str(value or "").strip():
                    settings[field] = value
            name = str(rec.get("display_name") or "").strip()
            if name and name != winner.get("display_name"):
                aliases.append(name)
            aliases.extend(a for a in (rec.get("aliases") or ()) if a)

        merged["columns"] = columns
        merged["settings"] = settings
        merged["claim_number"] = columns.get(
            "claim_number", winner.get("claim_number") or "")
        merged["carrier"] = columns.get(
            "carrier", winner.get("carrier") or "")
        merged["status"] = "active" if active else winner.get("status", "")
        merged["aliases"] = list(dict.fromkeys(aliases))
        collapsed.append(merged)
    return collapsed


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
        logs_bid = tc.get_logs_board_id()
        if logs_bid:
            # A Logs card is historical whether the caller asks us to
            # include it or not.  Previously we only recorded this id
            # inside the exclusion branch, so a full-history sync could
            # incorrectly reactivate every closed job it imported.
            closed_board_ids.add(logs_bid)
            if exclude_logs:
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
            values = _card_values(card)
            cols = _card_columns(tc, card, values)
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
                # Non-column values (links, other contacts, notes and scope)
                # stay as lightweight text metadata in the shared record.
                "settings":     values,
            }))
            if progress_cb is not None:
                try:
                    progress_cb(ci, len(cards), name)
                except Exception:
                    pass

    return {"boards": len(boards), "records": records}
