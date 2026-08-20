"""Naming convention: two shapes, four fields, three systems.

    multi-site   Trello  Parent - Site - Room - Date
                 Folder  Site - Room - Date
                 CC      Site - Room

    multi-claim  Trello  Name - Carrier - Nth Claim
                 Folder  Nth Claim
                 CC      Name - Nth Claim

The Trello card is the source because it is the only record carrying all
the fields. Every string below is a live card, folder or project name.
"""
import pytest

import commercial_naming_audit as a


# ── multi-site ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("card,parent,tr,od,cc", [
    # The exemplar.
    ("Menifee Union School District - Callie Kirkpatrick Elementary "
     "- 6/9/26 - Room 33", "Menifee Union School District",
     "Menifee Union School District - Callie Kirkpatrick Elementary "
     "- Room 33 - 6/9/26",
     "Callie Kirkpatrick Elementary - Room 33 - 6.9.26",
     "Callie Kirkpatrick Elementary - Room 33"),
    # Fields out of order, client in parentheses, date first.
    ("Menifee Union School District (8/14- Kirkpatrick) - Room 9",
     "Menifee Union School District",
     "Menifee Union School District - Kirkpatrick - Room 9 - 8/14/26",
     "Kirkpatrick - Room 9 - 8.14.26",
     "Kirkpatrick - Room 9"),
    # Several rooms on one job.
    ("Menifee Union School District (Freedom Crest) RM - 29,30 & 33- 7/29/26",
     "Menifee Union School District",
     "Menifee Union School District - Freedom Crest - Rooms 29,30,33 "
     "- 7/29/26",
     "Freedom Crest - Rooms 29,30,33 - 7.29.26",
     "Freedom Crest - Rooms 29,30,33"),
    # No rooms at all — the field is dropped, not left blank.
    ("Coreland Company - Dicks Sporting Goods - 3/19/26", "Coreland Company",
     "Coreland Company - Dicks Sporting Goods - 3/19/26",
     "Dicks Sporting Goods - 3.19.26",
     "Dicks Sporting Goods"),
    # A unit rather than a room.
    ("Metro at Main - Unit 214 - 5/2/26", "Metro at Main",
     "Metro at Main - Unit 214 - 5/2/26",
     "Unit 214 - 5.2.26",
     "Unit 214"),
])
def test_site_shape(card, parent, tr, od, cc):
    t = a.targets(card, parent)
    assert t["kind"] == "site"
    assert t["trello"] == tr
    assert t["folder"] == od
    assert t["companycam"] == cc


def test_the_client_is_stripped_even_in_a_different_word_order():
    """Folder 'Avana Springs Greystar' vs card 'Greystar - Avana Springs'.

    A literal prefix match fails, and the client's own name then ends up
    duplicated INTO the site: 'Avana Springs Greystar - Greystar Avana
    Springs - Unit 585G'.
    """
    t = a.targets("Greystar - Avana Springs (Unit 585G)",
                  "Avana Springs Greystar")
    assert t["trello"] == "Avana Springs Greystar - Unit 585G"
    assert t["folder"] == "Unit 585G"


def test_a_client_fused_into_the_first_segment_is_stripped():
    """'Coreland (Nordstrom Rack - Back Room)' has no clean prefix to cut,
    so the client survived into the site name."""
    t = a.targets("Coreland (Nordstrom Rack - Back Room) - 4/1//26",
                  "Coreland Company")
    assert t["folder"] == "Nordstrom Rack Back Room - 4.1.26"


def test_a_doubled_date_separator_leaves_no_debris():
    """'4/1//26' is live. Consuming only '4/1' left a stray '26' behind,
    which then read as part of the site name."""
    t = a.targets("Coreland (Nordstrom Rack) - 4/1//26", "Coreland Company")
    assert "26" not in t["companycam"]
    assert t["folder"].endswith("4.1.26")


def test_a_field_the_card_never_states_stays_empty():
    """Inventing a date is worse than omitting one."""
    t = a.targets("Coreland Company - Stacked Restaurant", "Coreland Company")
    assert t["folder"] == "Stacked Restaurant"
    assert t["date_slash"] == ""


# ── multi-claim ────────────────────────────────────────────────────────

@pytest.mark.parametrize("card,parent,tr,od,cc", [
    ("Nathan Bupte - AAA - 1st claim", "Nathan Bupte",
     "Nathan Bupte - AAA - 1st Claim", "1st Claim",
     "Nathan Bupte - 1st Claim"),
    ("Mansolino, Sayra- AAA - 1st Claim:Bathroom/Garage", "Mansolino Sayra",
     "Mansolino, Sayra - AAA - 1st Claim", "1st Claim",
     "Mansolino, Sayra - 1st Claim"),
    ("Bidwell, Doyle - AAA (3rd Claim)", "Bidwell Doyle",
     "Bidwell, Doyle - AAA - 3rd Claim", "3rd Claim",
     "Bidwell, Doyle - 3rd Claim"),
    # "Claim 2" and "2nd loss" both mean the second claim.
    ("Giles, Marcus - Claim 2 (Fire)", "Giles Marcus",
     "Giles, Marcus - 2nd Claim", "2nd Claim", "Giles, Marcus - 2nd Claim"),
])
def test_claim_shape(card, parent, tr, od, cc):
    t = a.targets(card, parent)
    assert t["kind"] == "claim"
    assert t["trello"] == tr
    assert t["folder"] == od
    assert t["companycam"] == cc


def test_the_carrier_is_only_on_trello():
    """CompanyCam keeps the name but not the insurer."""
    t = a.targets("Nathan Bupte - AAA - 1st claim", "Nathan Bupte")
    assert "AAA" in t["trello"]
    assert "AAA" not in t["companycam"]
    assert "AAA" not in t["folder"]


def test_the_loss_description_is_not_part_of_the_name():
    """Removing the carrier and claim wording and keeping the REMAINDER
    dragged the description in — 'Mansolino, Sayra Bathroom Garage'."""
    t = a.targets("Mansolino, Sayra - AAA - 2nd Claim (Kitchen)",
                  "Mansolino Sayra")
    assert t["companycam"] == "Mansolino, Sayra - 2nd Claim"


@pytest.mark.parametrize("text", [
    "1st floor closet",              # Metro at Main — a floor, not a claim
    "2nd floor closet",
    "Robles, Lilia (3rd floor)",
    "Metro at Main - Unit 214 - 5/2/26",
])
def test_an_ordinal_alone_is_not_a_claim(text):
    """A bare ordinal must not trigger the claim shape, or three floors
    of Metro at Main become three claims."""
    assert a.claim_ordinal(text) == ""


def test_rooms_are_identity_not_just_another_token():
    """Room 9 and Room 33 differ by one short token, so plain overlap
    scored them near-identical and handed each Kirkpatrick job the
    OTHER one's CompanyCam project."""
    assert a.score("Kirkpatrick - Room 9", "Kirkpatrick Room 33") == 0.0
    assert a.score("Kirkpatrick - Room 9", "Kirkpatrick Room 9") > 0.5


# ── the card that doesn't say which claim ──────────────────────────────

@pytest.mark.parametrize("card,parent", [
    ("Riley, Robert -Safeco", "Riley, Robert"),
    ("Giles, Marcus - Farmers", "Giles Marcus"),
])
def test_a_bare_carrier_is_not_a_site(card, parent):
    """Giles Marcus has folders 'Claim 1 (water)' and 'Claim 2 (Fire)' and
    two cards BOTH named 'Giles, Marcus - Farmers'. With no claim ordinal
    the site shape kicked in and proposed a folder called 'Farmers' — a
    carrier is not a place, and which card is which claim is not in the
    data. Ask rather than guess.
    """
    t = a.targets(card, parent)
    assert t["kind"] == "unclear"
    assert t["folder"] == "" and t["companycam"] == "" and t["trello"] == ""


def test_a_real_site_that_merely_mentions_a_carrier_still_works():
    """The guard must catch a card that is ONLY a carrier, not any card
    whose site happens to contain one."""
    t = a.targets("Coreland Company - Dicks Sporting Goods - 3/19/26",
                  "Coreland Company")
    assert t["kind"] == "site"
    assert t["folder"] == "Dicks Sporting Goods - 3.19.26"
