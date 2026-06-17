"""xa_inquiry_scan.is_inquiry_note — the 'questions + requests' classifier
that decides which XA notification notes become review-gated inquiry
candidates for the Inquiries & Disputes tracker.

The hard requirement: adjuster questions/requests flag True, but our OWN
staff status notes (which often contain "please note,…" or describe
completed work) must NOT — otherwise the queue floods.
"""
import xa_inquiry_scan as xi


def test_questions_flag_true():
    assert xi.is_inquiry_note(
        "Is any mitigation actually needed? Are you able to handle repair?")
    assert xi.is_inquiry_note("Do we need testing for the baseboards?")


def test_action_requests_flag_true():
    assert xi.is_inquiry_note("Please provide the sub bid asap.")
    assert xi.is_inquiry_note("Can you confirm coverage has been extended?")
    assert xi.is_inquiry_note("Let me know if you need anything else from us.")


def test_staff_status_notes_flag_false():
    assert not xi.is_inquiry_note(
        "Initial Inspection performed Wednesday by Supervisor Fernando Baca.")
    assert not xi.is_inquiry_note(
        "Monitor completed. Final mold wipe down to follow. Regards,")
    assert not xi.is_inquiry_note(
        "We will engage safeguard for Lead/Asbestos Testing.")


def test_please_note_is_not_a_request():
    # The classic false-positive: a staff note that opens "Please note,…".
    assert not xi.is_inquiry_note(
        "Please note, an initial inspection note was previously uploaded.")


def test_empty_is_false():
    assert not xi.is_inquiry_note("")
    assert not xi.is_inquiry_note("   ")


def test_first_sentence_prefers_question():
    s = xi._first_sentence("Good morning. Is mitigation needed? Thanks.")
    assert s.endswith("?")
    assert "mitigation needed" in s
