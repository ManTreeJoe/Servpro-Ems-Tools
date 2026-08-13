"""The carrier suffix is stripped however the dash is spaced.

`canon_key` is the PRIMARY KEY of `jobs`, so a name that canon'd two ways
was two jobs for one insured. The old rule only stripped a SINGLE-word
tail on the no-space variants — and most carriers are two words — so
"Smith, John - State Farm" and "Smith, John- State Farm" were separate
jobs. Nine rows on the live index were sitting on such a key, unreachable
by their own display name.

The fix is deliberately narrow: strip only when the tail is a carrier we
actually recognise. A blanket "split at the first spaced dash" was tried
against the live index first and folded every unit of a complex and every
school in a district onto one key — see the non-carrier tests below,
which are the cases that measurement turned up.
"""
import pytest

from ems_db_common import canon_key


PEOPLE = ["Smith, John", "Mahlmeister, Bonnie", "Ortega, Benigno"]
MULTI_WORD_CARRIERS = ["State Farm", "Self Pay", "Liberty Mutual"]
SINGLE_WORD_CARRIERS = ["AAA", "Mercury", "USAA"]


@pytest.mark.parametrize("person", PEOPLE)
@pytest.mark.parametrize("carrier", MULTI_WORD_CARRIERS + SINGLE_WORD_CARRIERS)
def test_every_dash_spacing_gives_one_key(person, carrier):
    """The bug in one assertion: four spellings, one job."""
    keys = {
        canon_key(f"{person} - {carrier}"),
        canon_key(f"{person}- {carrier}"),
        canon_key(f"{person} -{carrier}"),
        canon_key(person),
    }
    assert keys == {canon_key(person)}, (
        f"{person!r} + {carrier!r} canon'd {len(keys)} different ways: {keys}")


@pytest.mark.parametrize("carrier", SINGLE_WORD_CARRIERS)
def test_single_word_carriers_still_strip(carrier):
    """Regression guard — these already worked; the fix is additive."""
    assert canon_key(f"Smith, John- {carrier}") == "smith, john"


# Every one of these is a REAL name from the live job index. The dash is
# not reserved for carriers, and folding these would merge distinct jobs.
@pytest.mark.parametrize("name", [
    "Avila Apartments- Unit 226",
    "Temecula Creek Inn -Unit 225",
    "Keystone- Highland Village- (Unit 168)",
    "Menifee Union School District -Callie Kirkpatrick Elementary",
    "MUSD Oak Meadows Elementary- 2511-565898WTR",
    "Bell Mountain Middle School -2507388588WTR",
    "Meadowview Apartments- 7-7-26",
    "McSweeny Farms- 6/9/26",
])
def test_a_non_carrier_tail_is_never_stripped(name):
    """These identify the job. "Avila Apartments" alone is every unit."""
    assert canon_key(name).strip(), "canon_key must not blank the name"
    tail = name.split("-")[-1].strip().casefold()
    assert tail in canon_key(name), (
        f"{name!r} lost {tail!r} — that tail IS the job's identity")


def test_the_district_does_not_swallow_its_schools():
    """A blanket dash-split folded every school onto the district."""
    a = canon_key("Menifee Union School District -Callie Kirkpatrick Elementary")
    b = canon_key("Menifee Union School District -Oak Meadows Elementary")
    assert a != b


def test_units_of_one_complex_stay_distinct():
    assert canon_key("Avila Apartments- Unit 226") != \
           canon_key("Avila Apartments- Unit 227")


@pytest.mark.parametrize("name", [
    "Smith-Jones, Bob",
    "Nguyen, Kim-Ly",
    "Smith, John-Self Pay",       # no space either side — not a suffix
])
def test_a_hyphenated_name_is_left_alone(name):
    """No whitespace on either side of the dash means it is part of the
    name. This is the case `carriers.is_known` was written to protect."""
    assert canon_key(name) == " ".join(name.split()).casefold()


def test_7_eleven_keeps_its_number():
    """A blanket split reduced "7 -11  (Norco)" to "7"."""
    assert canon_key("7 -11  (Norco)").startswith("7 -11")


def test_blank_and_falsy():
    assert canon_key("") == ""
    assert canon_key(None) == ""
    assert canon_key("   ") == ""


def test_carrier_only_name_is_not_emptied():
    """Stripping must never leave nothing behind — an empty key would
    collide with every other empty key."""
    assert canon_key("State Farm") == "state farm"
