"""📧 Copy email finds the address wherever the card keeps it.

trello_enrichment only read CUSTOMER INFORMATION, so on a card that put
the insured's email under INSURED INFORMATION / PROPERTY DETAILS /
CONTACT INFORMATION the address was plainly visible on the card while the
button stayed disabled. docusign_requests had already learned the layouts
vary; the enrichment now falls back to its list instead of keeping a
second, shorter one.
"""
import pytest

import docusign_requests as ds


def _card(desc):
    return {"desc": desc}


@pytest.mark.parametrize("section", [
    "CUSTOMER INFORMATION",
    "INSURED INFORMATION",
    "PROPERTY DETAILS",
    "CONTACT INFORMATION",
])
def test_email_found_in_each_section_layout(section):
    got = ds.extract_insured_email(_card(f"**{section}**\nEMAIL: a@x.com"))
    assert got == "a@x.com"


@pytest.mark.parametrize("key", ["EMAIL", "CUSTOMER EMAIL", "INSURED EMAIL"])
def test_email_found_under_each_key_spelling(key):
    got = ds.extract_insured_email(
        _card(f"**CUSTOMER INFORMATION**\n{key}: b@x.com"))
    assert got == "b@x.com"


def test_mailto_prefix_is_stripped():
    """Trello stores these as mailto: links; copying that would paste a
    URL scheme into the To: field."""
    got = ds.extract_insured_email(
        _card("**INSURED INFORMATION**\nEMAIL: mailto:c@x.com"))
    assert got == "c@x.com"


def test_no_email_returns_empty_not_a_url():
    """The field sometimes holds a website. Copy email must not hand back
    "https://…" — the button stays disabled instead."""
    got = ds.extract_insured_email(
        _card("**CUSTOMER INFORMATION**\nEMAIL: https://example.com"))
    assert "@" not in got


def test_missing_desc_is_not_an_error():
    assert ds.extract_insured_email(_card("")) == ""
    assert ds.extract_insured_email(None) == ""


def test_contact_email_roles_remain_separate():
    card = _card("""**CUSTOMER INFORMATION**
EMAIL: insured@example.com
**ACCOUNT INFO**
POINT OF CONTACT EMAIL: manager@example.com
**TENANT INFORMATION**
EMAIL: tenant@example.com
**INSURANCE INFORMATION**
ADJUSTER EMAIL: adjuster@carrier.com
""")
    contacts = ds.extract_contact_emails(card)
    assert [(c["kind"], c["email"]) for c in contacts] == [
        ("Customer", "insured@example.com"),
        ("Property manager / POC", "manager@example.com"),
        ("Tenant", "tenant@example.com"),
        ("Adjuster", "adjuster@carrier.com"),
    ]


def test_internal_servpro_email_is_not_offered_as_job_contact():
    contacts = ds.extract_contact_emails(_card(
        "**ACCOUNT INFO**\nPOINT OF CONTACT EMAIL: ems@servpro10100.com"))
    assert contacts == []
