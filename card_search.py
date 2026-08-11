"""Finding the right Trello card by name.

Two things were wrong with searching for a card to pin.

**Partial words found nothing.** Trello's `/search` matches whole words.
Typing "garci" returned zero, and its `*` wildcard is no help — `garcia*`
works but `garci*`, `smit*` and `mongu*` all return nothing, so you had
to type the name exactly right before anything appeared.

**Relevance was being thrown away.** Trello searches card descriptions
and comments as well as names, so "david smith" legitimately returns
`Whaley, John -Allstate-WILDFIRE` — a card that merely mentions those
words somewhere. Trello ranks it below the real `Smith, David` card, but
sorting the results by board tier discarded that ranking and floated the
wrong card to the top because its board happened to be active.

So: match against the card NAME (this is find-card-by-NAME), score how
well it matches, and rank by score inside each tier rather than letting
the tier decide alone.

The local half searches `job_lifecycle` — 3,175 cards already mirrored
in the DB, with board and list. That is what makes partial words work at
all, and it answers instantly with no API call.
"""
import re

_PUNCT = re.compile(r"[^a-z0-9]+")


def normalize(s):
    return _PUNCT.sub(" ", str(s or "").casefold()).strip()


def tokens(s):
    return [t for t in normalize(s).split() if t]


def match_score(query, name):
    """0.0 (no match) … 1.0+ for how well `name` answers `query`.

    EVERY query token must be found, as a prefix of some token in the
    name — that is what makes "garci" find Garcia and "mongu" find
    Mongue. Requiring all of them is what keeps "david smith" from
    matching every card containing only the word "smith".

    Word order is ignored, so "david smith" and "smith david" both find
    `Smith, David - Mercury` — the office writes it both ways.
    """
    q = tokens(query)
    n = tokens(name)
    if not q or not n:
        return 0.0
    total = 0.0
    for qt in q:
        best = 0.0
        for nt in n:
            if nt == qt:
                best = 1.0
                break
            if nt.startswith(qt):
                # A near-complete prefix ("garci" of "garcia") should beat
                # a token that merely happens to start the same way.
                best = max(best, 0.6 + 0.4 * (len(qt) / len(nt)))
        if best == 0.0:
            return 0.0          # a token nothing in the name answers
        total += best
    score = total / len(q)
    # Nudge a name that STARTS with the query ahead of one that merely
    # contains it — "Smith, David" over "Davis-Smith, Felicia".
    if normalize(name).startswith(normalize(query)):
        score += 0.25
    return score


def search_local(query, limit=60):
    """Cards from the local mirror, out of BOTH places one is recorded.

    `job_lifecycle` is the Trello-card mirror (3,175 rows, with board and
    list) but it lags: recent jobs like Mongue and Kavuri were not in it,
    so a search for them found nothing at all.

    `jobs` + `job_links.trello_card` is the job index — the source of
    truth for which card belongs to which job — and it had both. It
    carries no board name, which is fine: an unknown board tiers as
    ACTIVE, and a job we hold a pin for is live work by definition.

    Returns the same shape `trello_client.find_cards_by_name` does, so
    the two can be merged without special-casing either.
    """
    q = tokens(query)
    if not q:
        return []
    longest = max(q, key=len)
    like = f"%{longest}%"
    rows = []
    try:
        import sqlite3

        import ems_db_sqlite as _db
        conn = sqlite3.connect(_db.DB_PATH)
        conn.row_factory = sqlite3.Row
        # Cheap SQL prefilter on the longest token, then score in Python.
        # Scanning every row is affordable, but LIKE keeps it to a handful.
        rows += [(r["card_id"], r["client_display"], r["board_name"],
                  r["list_name"]) for r in conn.execute(
            "SELECT card_id, client_display, board_name, list_name "
            "FROM job_lifecycle WHERE LOWER(client_display) LIKE ? "
            "LIMIT 400", (like,))]
        rows += [(r["link_value"], r["display_name"], "", "") for r in
                 conn.execute(
            "SELECT j.display_name, l.link_value FROM jobs j "
            "JOIN job_links l ON l.canon_key = j.canon_key "
            "WHERE l.link_type = 'trello_card' "
            "AND LOWER(j.display_name) LIKE ? LIMIT 400", (like,))]
        conn.close()
    except Exception:
        return []

    out, seen = [], set()
    for card_id, name, board, lane in rows:
        name = name or ""
        if not card_id or card_id in seen:
            continue
        s = match_score(query, name)
        if s <= 0:
            continue
        seen.add(card_id)
        out.append({
            "card_id":   card_id,
            "name":      name,
            "board":     board or "",
            "list_name": lane or "",
            "url":       "",
            "_score":    s,
            "_source":   "local",
        })
    out.sort(key=lambda h: -h["_score"])
    return out[:limit]


def merge(local, remote, query):
    """One list, deduped on card_id, every hit scored on its NAME.

    Remote wins on duplicate ids — it carries the short URL and is the
    live truth about the card's board. Hits whose name does not answer
    the query are dropped: those are Trello's description and comment
    matches, which is not what a name search asked for.
    """
    by_id = {}
    for h in list(local or []) + list(remote or []):
        cid = h.get("card_id") or h.get("id") or ""
        if not cid:
            continue
        name = h.get("name") or ""
        score = h.get("_score")
        if score is None:
            score = match_score(query, name)
        if score <= 0:
            continue
        prev = by_id.get(cid)
        if prev is None or h.get("_source") != "local":
            merged = dict(h)
            merged["_score"] = max(score, (prev or {}).get("_score", 0.0))
            by_id[cid] = merged
    return list(by_id.values())
