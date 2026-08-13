"""Find jobs that are probably one insured under two spellings.

The job key is derived from the name, so "Seth Knudsen" and
"Knudsen, Seth - Mercury" are two identities for one person: the audit
reads one row while a Trello sync writes the other, and the carrier,
claim number and photos land on whichever the tool happened to resolve.

This only ever PROPOSES. Folding two people who share a surname is worse
than leaving them split — an office of Smiths is not a data problem — so
every pair is put in front of a person, and their answer is remembered.

`carriers_for` and friends deliberately refuse to fall through from a
direct hit to an alias, which is why aliases alone can't repair a pair
that already exists: the two rows have to be merged.
"""
from __future__ import annotations

import re


_SUFFIX_RE = re.compile(r"\s*[-–]\s*([A-Za-z0-9/&.' ]+)$")

# Trailing words that describe the JOB, not the person. Cards are titled
# "Greer, Tesal - Mercury - FIRE": the carrier and the loss type both get
# appended, and neither is part of who somebody is.
_NOT_A_NAME = {
    "fire", "water", "wtr", "mold", "smoke", "storm", "wind", "flood",
    "contents", "recon", "reconstruction", "commercial", "residential",
    "asbestos", "bio", "trauma", "sewage", "vandalism", "hail",
}


def _is_decoration(part: str) -> bool:
    """True when a trailing " - X" describes the job rather than names
    the person — a carrier we recognise, or a loss type.

    Punctuation alone can't tell "Michael-Mercury" (a carrier) from
    "Smith-Jones" (a surname), so this asks what the word IS rather than
    how it's punctuated. Anything unrecognised stays part of the name.
    """
    p = re.sub(r"\s+", " ", (part or "").strip())
    if not p:
        return False
    if p.lower() in _NOT_A_NAME:
        return True
    try:
        import carriers as _carriers
        return bool(_carriers.is_known(p))
    except Exception:
        return False


def _strip_carrier_suffix(text: str) -> str:
    """Drop trailing " - Carrier" / " - FIRE" parts, and only those.

    Repeats, because cards stack them, and can't rely on spacing:
    "Greer, Tesal - Mercury - FIRE", "Ensign, Michael-Mercury",
    "Ochoa, Edward- AAA" are all real. A hyphenated surname survives,
    because "Jones" is not a carrier or a loss type.
    """
    out = re.sub(r"\s+", " ", (text or "").strip())
    while True:
        m = _SUFFIX_RE.search(out)
        if not m or not _is_decoration(m.group(1)):
            return out
        out = out[:m.start()].strip()


def swapped_name(name: str) -> str:
    """"Knudsen, Seth" → "Seth Knudsen", and back. "" when the name has
    no clear two-part form.

    The carrier suffix is dropped first: cards are written
    "Knudsen, Seth - Mercury", and the carrier is not part of who
    somebody is.
    """
    n = re.sub(r"\s+", " ", (name or "").strip())
    if not n:
        return ""
    if "," in n:
        last, _, rest = n.partition(",")
        rest = _strip_carrier_suffix(rest)
        last = last.strip()
        return f"{rest} {last}" if last and rest else ""
    n = _strip_carrier_suffix(n)
    parts = n.split()
    # Only the unambiguous two-word case. "Miles, Bridgitte & Anthony" or
    # "Athena Management Property" are not a first and a last name, and
    # guessing at them produces pairs nobody can confirm.
    if len(parts) != 2:
        return ""
    return f"{parts[1]}, {parts[0]}"


def find_split_pairs(jobs, *, ignored=()) -> list:
    """[(a, b)] job dicts that look like one insured under two spellings.

    `jobs` is what `ems_db.iter_jobs()` returns. `ignored` holds pair keys
    a human has already said are different people.
    """
    try:
        from ems_db_common import canon_key
    except Exception:                                  # pragma: no cover
        from ems_db import canon_key

    by_key = {}
    for j in jobs or ():
        k = (j or {}).get("canon_key") or ""
        if k:
            by_key[k] = j

    seen, out = set(), []
    ignored = set(ignored or ())
    for j in by_key.values():
        key = j.get("canon_key") or ""
        sw = swapped_name(j.get("display_name") or key)
        if not sw:
            continue
        other = canon_key(sw)
        if not other or other == key or other not in by_key:
            continue
        sig = pair_key(key, other)
        if sig in seen or sig in ignored:
            continue
        seen.add(sig)
        a, b = sorted((key, other))
        out.append((by_key[a], by_key[b]))
    return out


def pair_key(a: str, b: str) -> str:
    """Stable id for a pair, order-independent — so "ignore this pair"
    survives whichever way round it is next seen."""
    return "::".join(sorted([(a or "").strip(), (b or "").strip()]))


def describe(a: dict, b: dict) -> dict:
    """What a person needs in order to answer "same insured?".

    Deliberately includes the facts that DIFFER as well as the names: two
    rows with different claim numbers are usually two real jobs, and two
    with the same carrier and address are usually one.
    """
    def side(j):
        return {
            "canon_key":    j.get("canon_key") or "",
            "display_name": j.get("display_name") or "",
            "carrier":      j.get("carrier") or "",
            "claim_number": j.get("claim_number") or "",
            "address":      j.get("address") or "",
            "phone":        j.get("phone") or "",
            "status":       j.get("status") or "",
            "department":   j.get("department") or "",
            "first_seen":   (j.get("first_seen_at") or "")[:10],
            "job_id":       j.get("job_id") or "",
        }

    sa, sb = side(a), side(b)
    conflicts = []
    for field in ("carrier", "claim_number", "address", "phone"):
        va, vb = (sa[field] or "").strip(), (sb[field] or "").strip()
        if va and vb and va.lower() != vb.lower():
            conflicts.append(field)
    agrees = [f for f in ("carrier", "claim_number", "address", "phone")
              if (sa[f] or "").strip()
              and (sa[f] or "").strip().lower() == (sb[f] or "").strip().lower()]
    return {
        "pair_key":  pair_key(sa["canon_key"], sb["canon_key"]),
        "a": sa, "b": sb,
        "conflicts": conflicts,
        "agrees":    agrees,
        # A different claim number on each side is the strongest signal
        # that these are two real jobs, not one typed twice.
        "likely_same": (not conflicts) and bool(agrees),
    }
