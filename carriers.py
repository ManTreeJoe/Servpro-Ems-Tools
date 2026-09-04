"""Carrier name canonicalization.

The carrier field is free text typed by whoever opened the job, so the
same insurer arrives spelled several ways — "AAA"/"aaa",
"State Farm"/"state farm", "Mercury"/"Mercury Insurance". That splits
counts, breaks grouping, and makes the field look messier than the data
actually is.

**This never rejects a value.** Most of the tail is real: Homesite,
Bamboo, Universal, Safeco, The Hartford, California Fair Plan, One
Alliance North America. New carriers show up constantly, so an unknown
name passes through with nothing but whitespace tidied. A closed list
would mangle exactly the entries that most need to be recorded
correctly.

Some entries in this field are not insurers at all: a third-party
administrator (TPA) handles claims on behalf of an insurer or a
self-insured entity like a city or school district. The adjuster really
does work for them, so a TPA is the right thing to have in the field —
it just isn't a carrier, and counting it as one overstates how many jobs
have real coverage identified. `kind()` tells them apart.
"""

import re


# Values that mean "no carrier" rather than naming one. Offered in the
# picker so the field can say WHY it is empty: nothing owes on this job
# (N/A) versus we simply don't know yet (Pending).
NOT_A_CARRIER = "N/A"
PENDING = "Pending"
SPECIAL_VALUES = (NOT_A_CARRIER, PENDING)


# Canonical spellings, keyed by their squashed form. Built from the
# spellings actually present in the live index, so it fixes what really
# gets typed rather than what might be.
_CARRIERS = [
    "AAA",
    "Allstate",
    "AEGIS",
    "American Family",
    "Bamboo",
    "California Fair Plan",
    "Farmers",
    "Homesite",
    "Liberty Mutual",
    "Mercury",
    "One Alliance North America",
    "Safeco",
    "State Farm",
    "The Hartford",
    "Universal",
    "USAA",
]

# Third-party administrators. They belong in this field — the adjuster
# works for them — but they are not the insurer, so anything counting
# "jobs with a carrier" should be able to exclude them.
TPAS = [
    "George Hills",
    "Sedgwick",
]

# Neither an insurer nor a TPA: the customer is paying.
SELF_PAY = "Self Pay"

_CANONICAL = _CARRIERS + TPAS + [SELF_PAY]

# Alternate spellings → canonical. Only folds confirmed by the user;
# anything ambiguous is deliberately absent so it passes through
# untouched rather than being guessed at.
_ALIASES = {
    "mercury insurance": "Mercury",
    "amfam": "American Family",
    "self": "Self Pay",
    "self-pay": "Self Pay",
    "selfpay": "Self Pay",
    "state farm insurance": "State Farm",
    "statefarm": "State Farm",
    "usaa general": "USAA",
    "triple a": "AAA",
    "aaa insurance": "AAA",
    # Assignments arrive titled "ACE", but for this office that IS AAA —
    # same claims, same adjusters. Left unfolded it splits one carrier
    # across two names in every report, filter and carrier chip.
    # (Nationally "ACE" is a different insurer; this is a local
    # convention of the assignment source, not a general truth.)
    "ace": "AAA",
    "ace insurance": "AAA",
    "libery mutual": "Liberty Mutual",
    "hartford": "The Hartford",
    "n/a": NOT_A_CARRIER,
    "na": NOT_A_CARRIER,
    "none": NOT_A_CARRIER,
    "pending": PENDING,
    "tbd": PENDING,
    "unknown": PENDING,
}

# "Possibly SF" is intentionally NOT folded to State Farm. It records a
# guess, and resolving it to a real carrier would launder that guess into
# a fact — the one thing this module must not do.


def _squash(s):
    """Casefold + collapse whitespace — the matching key."""
    return re.sub(r"\s+", " ", str(s or "").strip()).casefold()


_BY_SQUASH = {_squash(c): c for c in _CANONICAL}
_BY_SQUASH.update({_squash(k): v for k, v in _ALIASES.items()})


def normalize(value):
    """Return the canonical spelling of `value`, or the value itself
    (whitespace-tidied) when it isn't one we know.

    Unknown names are preserved verbatim — see the module note. Blank in,
    blank out; this never invents a carrier.
    """
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return ""
    return _BY_SQUASH.get(_squash(raw), raw)


_TPA_SQUASH = {_squash(t) for t in TPAS}


def kind(value):
    """Classify what's in the field:

      ""        blank
      "none"    N/A — nothing owes on this job
      "pending" waiting on the info
      "self"    Self Pay — the customer is paying
      "tpa"     a third-party administrator, not the insurer
      "carrier" an actual insurer (known OR unrecognised)

    An unrecognised name reports "carrier": new insurers appear all the
    time and treating them as unknown would undercount real coverage.
    """
    v = normalize(value)
    if not v:
        return ""
    if v == NOT_A_CARRIER:
        return "none"
    if v == PENDING:
        return "pending"
    if v == SELF_PAY:
        return "self"
    if _squash(v) in _TPA_SQUASH:
        return "tpa"
    return "carrier"


def is_tpa(value):
    """True for a third-party administrator rather than an insurer."""
    return kind(value) == "tpa"


def is_specified(value):
    """True when the field identifies who is handling the claim — a real
    carrier or a TPA. Use this rather than a bare truthiness check, or a
    job marked Pending counts as covered.
    """
    return kind(value) in ("carrier", "tpa", "self")


def is_known(value) -> bool:
    """True only when this is a name we actually recognise.

    A different question from `is_specified`, which asks what KIND of
    thing a value is and answers "carrier" for anything unrecognised — so
    is_specified("Jones") is True. Callers that must tell a carrier from
    an ordinary word need this: stripping a trailing " - Something" off a
    job name is right for "Greer, Tesal - Mercury" and wrong for
    "Mary Smith-Jones".
    """
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    return bool(raw) and _squash(raw) in _BY_SQUASH


def options():
    """Suggestions for the carrier picker, in the order they should show:
    the placeholders first (they answer "why is this empty?"), then
    Self Pay, then insurers, then TPAs — each with the group it belongs
    to so the picker can label it.

    Returns [{"value", "group"}]. The field stays FREE TEXT; this is a
    datalist, not a whitelist, so Lemonade and friends still type through.
    """
    out = [{"value": v, "group": "Status"} for v in SPECIAL_VALUES]
    out.append({"value": SELF_PAY, "group": "Self pay"})
    out += [{"value": c, "group": "Carrier"}
            for c in sorted(_CARRIERS, key=str.casefold)]
    out += [{"value": t, "group": "TPA (third-party administrator)"}
            for t in sorted(TPAS, key=str.casefold)]
    return out
