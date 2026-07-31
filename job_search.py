"""Type-ahead over job names. Database only — never touches disk.

The search box used to fire a FULL audit (`audit_jobs`: year-folder walk +
SharePoint scan + Trello lookups) as soon as you typed three characters,
against a single GUESSED canonical name. That is why it felt slow, and why
it gave one answer instead of a choice. This module answers the "which job
did you mean" question from the job index alone, so the expensive scan
happens once, after you pick.

Why a linear scan and not an index
----------------------------------
The corpus is ~410 job names plus ~450 aliases: under a thousand short
strings, scored in well under a millisecond. A trigram index, BK-tree or
similar would add an invalidation problem (the index would go stale on
every upsert_job) to buy speed that is already imperceptible. The cost
that mattered was the disk and network I/O, and that is now gone.

Why tiered matching and not edit distance
-----------------------------------------
Ranking by Levenshtein alone is actively wrong for this data. Job names
are filed surname-first — "Smith, John" — so:

  * typing "smith" scores "Smyth" (distance 1) above "Smith, John"
    (distance 6), even though the second is an exact prefix.
  * typing "john" never finds "Smith, John" at all without scanning
    tokens, because the distance to the whole string is enormous.

So matches are TIERED: an exact hit outranks a prefix, a prefix outranks a
word-start, and fuzzy similarity is only ever a last resort. Within a tier,
shorter names win (they are the more specific match) and recently-seen jobs
win over dormant ones, which is what you usually want when two clients
share a surname.
"""
import difflib
import re
import threading
import time

# Word-start matching is what makes "john" find "Smith, John", so the
# tokenizer has to split on the punctuation these names are full of:
# commas, hyphens, apostrophes, parentheses, dots in "5.13.26".
_SPLIT = re.compile(r"[^a-z0-9]+")

# Scores are spaced so no combination of tie-breakers can lift a lower
# tier above a higher one — a "recent" fuzzy hit must never outrank an
# exact match.
S_EXACT       = 1000
S_PREFIX      = 800
S_WORD_START  = 600
S_SUBSTRING   = 400
S_ALIAS_ONLY  = 150     # penalty applied when the hit came via an alias
S_FUZZY       = 200

# Below this, a fuzzy suggestion is noise rather than a typo.
_FUZZY_FLOOR = 0.72

_LOCK = threading.RLock()
_index = None
_built_at = 0.0

# The index is also dropped explicitly via cache_bust, but a TTL means a job
# created by any path — new loss, a one-off audit, a Trello sync — turns up
# in search on its own. Hooking every write site instead is exactly the kind
# of list that rots the first time someone adds a caller.
_TTL_S = 60.0


def _norm(s):
    return (s or "").strip().lower()


def _tokens(s):
    return [t for t in _SPLIT.split(_norm(s)) if t]


def invalidate_cache():
    """Drop the cached index. Wired into cache_bust so a new job, a rename
    or a backend switch is reflected on the next keystroke."""
    global _index, _built_at
    with _LOCK:
        _index = None
        _built_at = 0.0


def _build():
    """One pass over the job index: 2 queries total, never per-job."""
    import ems_db
    entries, by_key = [], {}
    for j in ems_db.iter_jobs():
        key = j.get("canon_key") or ""
        name = j.get("display_name") or key
        if not key:
            continue
        e = {"canon_key": key, "display_name": name,
             "norm": _norm(name), "tokens": _tokens(name),
             # Alias tokens are kept SEPARATE from the display name's.
             # Merging them let one bad alias hijack a search: live data has
             # "David Smith" recorded as an alias of "Bernardo, Froilan-AAA"
             # while a real "Smith, David - Mercury" job exists, and a merged
             # token list ranked Bernardo first for "smith".
             "alias_tokens": [],
             "aliases": [], "alias_norms": [],
             "last_seen": j.get("last_seen_at") or "",
             "department": j.get("department") or ""}
        entries.append(e)
        by_key[key] = e

    try:
        for row in ems_db.all_aliases():
            e = by_key.get(row.get("canon_key"))
            alias = row.get("alias") or ""
            if not e or not alias:
                continue
            n = _norm(alias)
            # An alias identical to the display name adds nothing to rank
            # against and would just duplicate work on every keystroke.
            if n and n != e["norm"] and n not in e["alias_norms"]:
                e["aliases"].append(alias)
                e["alias_norms"].append(n)
                for t in _tokens(alias):
                    if t not in e["tokens"] and t not in e["alias_tokens"]:
                        e["alias_tokens"].append(t)
    except Exception:
        # Aliases are a ranking bonus, not a requirement. A backend that
        # can't serve them should still give you name search.
        pass

    # Character bigrams, precomputed once, used to skip entries that cannot
    # possibly be a near-miss before paying for SequenceMatcher.
    for e in entries:
        b = set()
        for t in e["tokens"] + e["alias_tokens"] + [e["norm"]]:
            b.update(_bigrams(t))
        e["bigrams"] = b
    return entries


def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def _get_index():
    global _index, _built_at
    with _LOCK:
        if _index is None or (time.monotonic() - _built_at) > _TTL_S:
            _index = _build()
            _built_at = time.monotonic()
        return _index


def _term_score(e, term):
    """Best tier for ONE query word against an entry's words."""
    if any(t == term for t in e["tokens"]):
        return S_EXACT
    if any(t.startswith(term) for t in e["tokens"]):
        return S_WORD_START
    if any(term in t for t in e["tokens"]):
        return S_SUBSTRING
    if any(t.startswith(term) for t in e["alias_tokens"]):
        return S_WORD_START - S_ALIAS_ONLY
    return 0


def _score_multi(e, terms, q):
    """Score a multi-word query — "david smith", "smith john".

    Every word must match something, which is what makes the result
    precise; nothing about the ORDER is required, because these names are
    filed surname-first and people type them both ways round. Without this
    the whole query was matched as one string, so "david smith" could never
    reach "Smith, David - Mercury" and only found it by luck through an
    alias.
    """
    total = 0
    for term in terms:
        s = _term_score(e, term)
        if not s:
            return None                 # AND, not OR — one miss disqualifies
        total += s
    score = total // len(terms)
    if q in e["norm"]:                  # typed in the same order as filed
        score += 50
    return score, "matches"


def _score_one(e, q):
    """Best (score, why) for one entry, or None. Highest tier wins."""
    if e["norm"] == q:
        return S_EXACT, "exact"
    if q in e["alias_norms"]:
        return S_EXACT - S_ALIAS_ONLY, "also known as"
    if e["norm"].startswith(q):
        return S_PREFIX, "starts with"
    if any(a.startswith(q) for a in e["alias_norms"]):
        return S_PREFIX - S_ALIAS_ONLY, "also known as"
    if any(t.startswith(q) for t in e["tokens"]):
        return S_WORD_START, "word match"
    if any(t.startswith(q) for t in e["alias_tokens"]):
        return S_WORD_START - S_ALIAS_ONLY, "also known as"
    if q in e["norm"]:
        return S_SUBSTRING, "contains"
    if any(q in a for a in e["alias_norms"]):
        return S_SUBSTRING - S_ALIAS_ONLY, "also known as"
    return None


# An alias-derived fuzzy hit is two inferences deep — a guess at a typo of
# a nickname — so it is scaled down rather than merely offset, keeping it
# below any fuzzy hit on the job's own name.
_ALIAS_FUZZY_SCALE = 0.65


def _fuzzy_score(e, q, matcher):
    """Typo tolerance, checked only when the real tiers came up short.

    Compared against each TOKEN as well as the whole name: "smiht" should
    reach "Smith, John" via the surname, since its ratio against the full
    string is far too low to notice.

    `matcher` already holds q as seq2; difflib caches that side's index, so
    reusing it avoids re-indexing the query for all 412 entries.
    """
    def ratio(s):
        matcher.set_seq1(s)
        return matcher.ratio()

    best, from_alias = ratio(e["norm"]), False
    for t in e["tokens"]:
        if abs(len(t) - len(q)) > 3:
            continue                      # can't be a plausible typo
        r = ratio(t)
        if r > best:
            best, from_alias = r, False
    for t in e["alias_tokens"]:
        if abs(len(t) - len(q)) > 3:
            continue
        r = ratio(t) * _ALIAS_FUZZY_SCALE
        if r > best:
            best, from_alias = r, True
    if best < _FUZZY_FLOOR:
        return None
    return int(S_FUZZY * best), ("did you mean" if not from_alias
                                 else "also known as")


def suggest(query, limit=8):
    """Ranked candidates for a typed fragment. Pure DB read, no I/O.

    Returns [{canon_key, display_name, why, aliases, department}].
    """
    q = _norm(query)
    if len(q) < 2:
        return []

    terms = _tokens(q)
    multi = len(terms) > 1

    hits = []
    for e in _get_index():
        got = _score_multi(e, terms, q) if multi else _score_one(e, q)
        if got:
            hits.append((got[0], got[1], e))

    # Fuzzy is a FALLBACK, not a parallel tier: running it always would let
    # a near-miss crowd out real matches, and it is the expensive path.
    # Single-word queries only — it compares the query against one token at
    # a time, so measuring "david smith" against "smith" is meaningless, and
    # multi-word queries already match generously per term.
    if len(hits) < limit and not multi:
        seen = {id(e) for _s, _w, e in hits}
        qb = _bigrams(q)
        # difflib caches the index for seq2 only, so q goes there ONCE and
        # each candidate is swapped through seq1.
        matcher = difflib.SequenceMatcher(None, "", q)
        for e in _get_index():
            if id(e) in seen:
                continue
            # A typo shares character bigrams with its target. Entries with
            # none cannot clear the floor, and skipping them here is what
            # keeps the fallback off the full corpus.
            if not (qb & e["bigrams"]):
                continue
            got = _fuzzy_score(e, q, matcher)
            if got:
                hits.append((got[0], got[1], e))

    # Tie-breakers, applied only WITHIN a tier: shorter name first (the
    # more specific match), then most recently seen — which is what
    # separates two clients who share a surname.
    hits.sort(key=lambda h: (-h[0], len(h[2]["norm"]),
                             _neg_str(h[2]["last_seen"])))
    out = []
    for score, why, e in hits[:limit]:
        out.append({"canon_key": e["canon_key"],
                    "display_name": e["display_name"],
                    "why": why, "score": score,
                    "aliases": e["aliases"][:3],
                    "department": e["department"]})
    return out


class _neg_str:
    """Sort a string DESCENDING inside an otherwise ascending key."""
    __slots__ = ("s",)

    def __init__(self, s):
        self.s = s or ""

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == other.s
