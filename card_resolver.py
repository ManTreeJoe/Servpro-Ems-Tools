"""Shared Trello card resolver — single source of truth for the
3-step lookup chain every panel was duplicating:

  1. Explicit `card_id` (caller hands one in — the row's card_id,
     usually) — preferred, skip everything else.
  2. `persistence.get_trello_card_id(client)` — the pinned card,
     authoritative across the suite.
  3. `trello_client.find_cards_by_name(client)` — last-resort
     fuzzy search (returns the highest-scoring hit's card_id).

Used by every flow that needs a card_id given a client name:
Docusketch request, CLOSE OUT checklist load, Trello attachments,
post comment, etc. Pulls the chain out of each web Api so every
caller stays in sync.
"""
from __future__ import annotations


def resolve(client: str = "", card_id: str = "") -> tuple[str, str]:
    """Resolve a Trello card_id for `client` using the canonical
    fallback chain. Returns (card_id, error_message). `card_id` is
    "" on miss; `error_message` is "" on hit.

    Caller chooses how to surface the error — most panels show a
    "No Trello card found for X. Pin one first." toast.

    Args mirror the convention every panel was using:
      • `client`  — the canonical / typed name (may be a slight
                    variant of the card's title)
      • `card_id` — explicit override; skips the chain when set
    """
    cid = (card_id or "").strip()
    if cid:
        return cid, ""

    name = (client or "").strip()
    if not name:
        return "", "no client or card_id"

    # Step 2: pinned card
    try:
        import persistence as _per
        pinned = (_per.get_trello_card_id(name) or "").strip()
        if pinned:
            return pinned, ""
    except Exception:
        pass

    # Step 3: fuzzy search — uses Trello's built-in name match. Take
    # the first (highest-scoring) hit; downstream callers tolerate
    # a wrong match better than no match, and the user can verify
    # via the card name shown in the resulting modal.
    try:
        import trello_client as _tc
        hits = _tc.find_cards_by_name(name, max_results=1) or []
        if hits:
            cid = (hits[0].get("card_id") or hits[0].get("id") or "").strip()
            if cid:
                return cid, ""
    except Exception as ex:
        return "", f"Trello search failed: {ex}"

    return "", f"no Trello card found for '{name}'. Pin one first."
