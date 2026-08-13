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
            claim = ""
            carrier = ""
            try:
                fields = tc.parse_card_desc(card.get("desc") or "")
                ins = fields.get("INSURANCE INFORMATION") or {}
                claim = (ins.get("CLAIM NUMBER") or "").strip()
                carrier = (ins.get("INSURANCE COMPANY") or "").strip()
            except Exception:
                pass
            # Canonicalise on the way in. Cards carry "farmers", "Farmers"
            # and "FARMERS" for one carrier, and storing them as typed is
            # why backfill_carriers.py had to exist to tidy up afterwards.
            # normalize() leaves anything it doesn't recognise alone, so
            # this never invents a carrier.
            if carrier:
                try:
                    import carriers as _carriers
                    carrier = _carriers.normalize(carrier) or carrier
                except Exception:
                    pass

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
            }))
            if progress_cb is not None:
                try:
                    progress_cb(ci, len(cards), name)
                except Exception:
                    pass

    return {"boards": len(boards), "records": records}
