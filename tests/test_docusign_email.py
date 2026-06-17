"""docusign_requests — the closeout DocuSign request email sent to the
insured. The property city is auto-filled from the job's address; the
'📝 Copy DS email' button on the snapshot form copies the result.
"""
import docusign_requests as dsr


def test_city_from_comma_less_address():
    assert dsr.city_from_address("5671 Northwood Dr. Riverside 92509") == "Riverside"


def test_city_multi_word():
    assert dsr.city_from_address("2146 Marigold Ct San Jacinto 92582") == "San Jacinto"
    assert dsr.city_from_address("456 Oak Ave Moreno Valley 92553") == "Moreno Valley"


def test_city_with_state_and_commas():
    assert dsr.city_from_address("123 Main St, Riverside, CA 92509") == "Riverside"
    assert dsr.city_from_address("100 First St, Corona CA 92879") == "Corona"


def test_city_strips_unit_token():
    assert dsr.city_from_address("789 Elm Blvd Apt 4 Riverside 92501") == "Riverside"


def test_city_blank_when_unparseable():
    assert dsr.city_from_address("") == ""
    assert dsr.city_from_address(None) == ""


def test_email_text_has_city_and_phone():
    txt = dsr.customer_email_text("Riverside")
    assert "in Riverside" in txt
    assert "951-398-3240" in txt
    assert txt.startswith("Hello, as Servpro has completed mitigation services")
    assert "close out this part of your claim" in txt


def test_email_text_blank_city_drops_clause():
    txt = dsr.customer_email_text("")
    # No dangling "in " — the clause is omitted cleanly.
    assert "at your property, we will need" in txt
    assert " in " not in txt.split("we will need")[0]
