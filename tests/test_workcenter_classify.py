"""Loss-code classification — pure-logic tests, no Playwright/network.

The classifier gates whether the audit pulls files from a Workcenter
job shell. Misclassifying a Contents or Recon job as EMS would land
someone else's photos in our PICS folder, so the lists in
workcenter_client need to stay tight.
"""
from workcenter_client import (
    classify_loss_code, EMS_LOSS_CODES, NON_EMS_LOSS_CODES,
    JobMatch, _PROJECT_ID_RE,
)


def test_known_ems_codes_classify_as_ems():
    for c in ["WTR", "FIR", "MLD", "STO", "BIO"]:
        assert classify_loss_code(c) == "ems", c


def test_known_non_ems_codes_classify_as_non_ems():
    for c in ["CON", "REC", "CTS", "RCN"]:
        assert classify_loss_code(c) == "non_ems", c


def test_unknown_codes_surface_as_unknown_not_silently_dropped():
    # New SERVPRO codes should be visible to the caller, not silently
    # bucketed as non-EMS — that's how legitimate jobs would disappear.
    assert classify_loss_code("ZZZ") == "unknown"


def test_classify_handles_lowercase_and_empty():
    assert classify_loss_code("wtr") == "ems"
    assert classify_loss_code("") == "unknown"
    assert classify_loss_code(None) == "unknown"


def test_ems_and_non_ems_lists_are_disjoint():
    # Regression guard — adding a code to both lists would make the
    # classifier ambiguous and Python frozenset operations silent.
    assert not (EMS_LOSS_CODES & NON_EMS_LOSS_CODES)


def test_project_id_regex_splits_id_and_loss_code():
    m = _PROJECT_ID_RE.search("Project: 2604-202129WTR (water)")
    assert m is not None
    assert m.group(1) == "2604-202129"
    assert m.group(2) == "WTR"


def test_jobmatch_category_uses_classifier():
    assert JobMatch(project_id="2604-1WTR", loss_code="WTR").category == "ems"
    assert JobMatch(project_id="2604-1CON", loss_code="CON").category == "non_ems"
    assert JobMatch(project_id="2604-1ZZZ", loss_code="ZZZ").category == "unknown"


# ── Forms allowlist ───────────────────────────────────────────────────────────

from workcenter_client import (
    REQUIRED_FORM_NUMBERS, _form_number_from_text, _allow_form,
    _build_legacy_url, _extract_guids,
)


def test_form_number_extraction_from_row_text():
    assert _form_number_from_text("28000 - Auth to Perform Services") == ("28000", "")
    assert _form_number_from_text("28000-CA - Authorization to Perform") == ("28000", "CA")
    assert _form_number_from_text("28501 - California Customer Information Form - Water Damage") == ("28501", "")
    assert _form_number_from_text("Random row with no number") == (None, None)
    assert _form_number_from_text("") == (None, None)


def test_allow_form_required_without_suffix():
    # Plain Required forms always allowed regardless of carrier.
    for num in REQUIRED_FORM_NUMBERS:
        assert _allow_form(num, "", None) is True
        assert _allow_form(num, "", "Farmers Insurance") is True


def test_allow_form_rejects_unknown_numbers():
    assert _allow_form("99999", "", None) is False
    assert _allow_form("28999", "", "California Casualty") is False


def test_allow_form_carrier_specific_suffix():
    # CA variant blocked without a CA carrier...
    assert _allow_form("28000", "CA", None) is False
    assert _allow_form("28000", "CA", "AAA Insurance") is False
    # ...allowed when carrier matches.
    assert _allow_form("28000", "CA", "Farmers California") is True
    assert _allow_form("28000", "CA", "California Casualty") is True
    assert _allow_form("28000", "CA", "State Farm") is True


def test_allow_form_collision_28000_vs_28000_ca():
    # Regression — the audit's name regex would match "CA COS" as "COS"
    # because of \bcos\b. Workcenter pull must NOT do that — number-
    # based matching keeps the two variants distinct.
    assert _allow_form("28000",    "",   None) is True       # plain
    assert _allow_form("28000",    "CA", None) is False      # CA blocked w/o carrier


def test_extract_guids_from_title_link_href():
    href = ("https://workcenter-rm.servpronet.io/Jobs/JobDetail_RM"
            "?signin=oidc&regionGuid=df47d0b1-616c-487c-95d2-42d651e56374"
            "&jobGuid=6fbb36ff-7e96-4b77-8c33-465da4118251")
    region, job = _extract_guids(href)
    assert region == "df47d0b1-616c-487c-95d2-42d651e56374"
    assert job    == "6fbb36ff-7e96-4b77-8c33-465da4118251"


def test_extract_guids_handles_empty_or_partial_href():
    assert _extract_guids("") == ("", "")
    assert _extract_guids("https://example.com/no-guids-here") == ("", "")


def test_build_legacy_url_round_trips():
    url = _build_legacy_url("df47d0b1-616c-487c-95d2-42d651e56374",
                              "6fbb36ff-7e96-4b77-8c33-465da4118251")
    assert "regionGuid=df47d0b1-616c-487c-95d2-42d651e56374" in url
    assert "jobGuid=6fbb36ff-7e96-4b77-8c33-465da4118251" in url
    assert url.startswith("https://workcenter-rm.servpronet.io/")


def test_build_legacy_url_returns_empty_when_guids_missing():
    # Defensive — callers check truthiness of legacy_url before goto().
    assert _build_legacy_url("", "abc") == ""
    assert _build_legacy_url("abc", "") == ""
