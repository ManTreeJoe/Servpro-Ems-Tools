"""Trello clipboard cleanup — splits comments by author/timestamp header
and strips the per-comment "• Reply / • Add link as attachment" boilerplate
so the dump reads cleanly in the Job Notes editor."""
from job_notes_gui import clean_trello_paste


def test_passthrough_when_no_header():
    raw = "Just some loose plain-text notes\nwith two lines."
    # No Trello-style header → returned unchanged so generic pastes work.
    assert clean_trello_paste(raw) == raw


def test_passthrough_empty_string():
    assert clean_trello_paste("") == ""
    assert clean_trello_paste(None) is None


def test_strips_reply_and_attach_chrome():
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Sent the COS to the carrier.\n"
        "•\nReply and\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    assert "Reply" not in out
    assert "Add link as attachment" not in out
    assert "Sent the COS to the carrier." in out
    # Header should be present in the formatted form.
    assert "Laura Barajas" in out
    assert "Apr 27, 2026, 4:03 PM" in out


def test_splits_multiple_messages():
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Sent the COS.\n"
        "•\nReply\n•\nAdd link as attachment\n"
        "Joe Smith Apr 28, 2026, 9:15 AM\n"
        "Got it, thanks.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    # Both authors should be present and ordered
    assert out.index("Laura Barajas") < out.index("Joe Smith")
    # Both bodies should survive
    assert "Sent the COS." in out
    assert "Got it, thanks." in out
    # Boilerplate gone
    assert "Reply" not in out
    assert "Add link as attachment" not in out


def test_inline_reply_chrome_also_stripped():
    # Some pastes have the bullet+label on a single line.
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Body line.\n"
        "• Reply and • Add link as attachment\n"
        "Joe Smith Apr 28, 2026, 9:15 AM\n"
        "Reply received."
    )
    out = clean_trello_paste(raw)
    assert "Add link as attachment" not in out
    assert "Body line." in out
    # "Reply received" is the user's actual message body — must survive
    # even though "Reply" matches the chrome word.
    assert "Reply received." in out


def test_preserves_message_with_bullet_list_inside():
    # Real comments sometimes contain bullet lists. Only the literal
    # "• Reply" / "• Add link as attachment" lines should be stripped —
    # arbitrary bullets inside the body are left alone.
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Outstanding items:\n"
        "• Send COS\n"
        "• Get signed AOB\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    assert "• Send COS" in out
    assert "• Get signed AOB" in out
    assert "Add link as attachment" not in out


def test_strips_reaction_count_before_reply():
    """When a Trello comment has a reaction, the count copies as a bare
    digit on its own line right above the Reply chrome — the emoji
    that prefixes it in the UI doesn't always survive the clipboard.
    Strip the orphan count along with the chrome."""
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "@samantha10100 @laura75056847 @victoria88623582\n"
        "\n"
        "1\n"
        "\n"
        "Reply\n"
    )
    out = clean_trello_paste(raw)
    # Body content survives — including the @-mentions
    assert "@samantha10100" in out
    assert "@laura75056847" in out
    assert "@victoria88623582" in out
    # Reply chrome stripped even without bullet prefix
    assert "Reply" not in out
    # The orphan reaction count is gone (no stray "1" left)
    assert "\n1\n" not in out
    assert not out.rstrip().endswith("1")


def test_strips_reaction_count_with_bullet_reply():
    """Variant: reaction count followed by the classic "•\\nReply"
    bullet chrome. Both the count and the chrome should disappear."""
    raw = (
        "Joe Smith Apr 28, 2026, 9:15 AM\n"
        "Got it.\n"
        "2\n"
        "•\nReply\n•\nAdd link as attachment\n"
    )
    out = clean_trello_paste(raw)
    assert "Got it." in out
    assert "Reply" not in out
    assert "Add link as attachment" not in out
    # Standalone "2" reaction count gone too
    assert "\n2\n" not in out


def test_legit_number_in_body_survives():
    """Numbers inside a body — not adjacent to Reply chrome — must NOT
    be stripped. The strip is anchored to the chrome below."""
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Outstanding items:\n"
        "1. Send COS\n"
        "2. Get signed AOB\n"
        "Done.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    assert "1. Send COS" in out
    assert "2. Get signed AOB" in out


def test_strips_bare_reply_without_bullet():
    """Trello pastes occasionally have Reply on its own line with no
    bullet prefix — strip it. Body words containing 'Reply' must
    still survive (test_inline_reply_chrome_also_stripped covers
    that case explicitly)."""
    raw = (
        "Joe Smith Apr 28, 2026, 9:15 AM\n"
        "Quick note.\n"
        "Reply\n"
        "Add link as attachment\n"
    )
    out = clean_trello_paste(raw)
    assert "Quick note." in out
    assert "Reply" not in out
    assert "Add link as attachment" not in out


def test_three_part_author_name():
    # "Mark E Lopez" / "Mary Ann Smith" should still parse.
    raw = (
        "Mary Ann Smith Apr 27, 2026, 4:03 PM\n"
        "Hello from a three-name author.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    assert "Mary Ann Smith" in out
    assert "Hello from a three-name author." in out


def test_relative_time_one_hour_ago():
    # Trello's "1 hour ago" should resolve to the absolute time relative
    # to `now`. Lowercase Trello handle ("victoria") must also parse.
    from datetime import datetime
    now = datetime(2026, 4, 30, 10, 30)  # Thursday 10:30 AM
    raw = "victoria 1 hour ago\nThursday 4/30/2026"
    out = clean_trello_paste(raw, now=now)
    # Should rewrite to absolute: 1 hour before 10:30 = 9:30 AM
    assert "9:30 AM" in out
    assert "Apr 30, 2026" in out
    assert "victoria" in out
    assert "Thursday 4/30/2026" in out  # body survives


def test_relative_time_minutes_ago():
    from datetime import datetime
    now = datetime(2026, 4, 30, 10, 30)
    raw = "Joe 15 minutes ago\nQuick update."
    out = clean_trello_paste(raw, now=now)
    assert "10:15 AM" in out
    assert "Quick update." in out


def test_relative_time_just_now():
    from datetime import datetime
    now = datetime(2026, 4, 30, 14, 5)  # 2:05 PM
    raw = "victoria just now\nFresh comment."
    out = clean_trello_paste(raw, now=now)
    assert "2:05 PM" in out
    assert "Fresh comment." in out


def test_relative_time_yesterday():
    from datetime import datetime
    now = datetime(2026, 4, 30, 10, 0)
    raw = "Joe yesterday\nFollowup needed."
    out = clean_trello_paste(raw, now=now)
    # Yesterday → Apr 29, defaulting to noon since we don't know the time.
    assert "Apr 29, 2026" in out
    assert "Followup needed." in out


def test_mixed_relative_and_absolute_in_one_paste():
    from datetime import datetime
    now = datetime(2026, 4, 30, 10, 30)
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Old comment.\n"
        "•\nReply\n•\nAdd link as attachment\n"
        "victoria 1 hour ago\n"
        "New comment."
    )
    out = clean_trello_paste(raw, now=now)
    assert "Old comment." in out
    assert "New comment." in out
    assert "Laura Barajas" in out
    assert "victoria" in out
    # Both timestamps should appear
    assert "Apr 27, 2026, 4:03 PM" in out
    assert "9:30 AM" in out


# ── (edited) suffix on Trello comments ──────────────────────────────────────
# Trello adds " (edited)" after the timestamp on comments that were modified
# after posting. The cleanup must recognize the header in BOTH absolute and
# relative-time forms AND preserve the marker in the cleaned output so the
# user can still tell the comment was edited.

def test_absolute_header_with_edited_marker_recognized():
    raw = (
        "Mark Escobar Apr 28, 2026, 9:15 AM (edited)\n"
        "Updated my reply.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    # Header must be recognized — body must come through clean.
    assert "Updated my reply." in out
    assert "Reply" not in out  # boilerplate stripped
    assert "Add link as attachment" not in out
    # (edited) must survive in the rendered output.
    assert "(edited)" in out


def test_relative_header_with_edited_marker_recognized():
    """The case the user flagged: 'Mark Escobar 2 hours ago (edited)'.
    Should resolve to an absolute timestamp AND keep the edited marker."""
    from datetime import datetime
    now = datetime(2026, 4, 30, 10, 30)
    raw = (
        "Mark Escobar 2 hours ago (edited)\n"
        "Tweaked the wording.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw, now=now)
    assert "Tweaked the wording." in out
    # 2 hours before 10:30 AM = 8:30 AM absolute timestamp
    assert "8:30 AM" in out
    assert "(edited)" in out
    assert "Mark Escobar" in out


def test_edited_marker_does_not_break_message_split():
    """When one of multiple messages has (edited), the splitter must
    still cut on each header and not glue them together."""
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "First message.\n"
        "•\nReply\n•\nAdd link as attachment\n"
        "Mark Escobar Apr 28, 2026, 9:15 AM (edited)\n"
        "Second message.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    assert "First message." in out
    assert "Second message." in out
    # The edited marker stays attached to Mark's header, not Laura's.
    assert "9:15 AM (edited)" in out
    assert "4:03 PM (edited)" not in out


def test_header_without_edited_still_works():
    """Sanity: the optional (edited) group doesn't break plain headers."""
    raw = (
        "Laura Barajas Apr 27, 2026, 4:03 PM\n"
        "Plain unedited comment.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw)
    assert "Plain unedited comment." in out
    assert "(edited)" not in out


# Cover the "etc" matrix — every unit Trello uses, with and without
# (edited), so future regex tweaks can't quietly drop a variant.
import pytest
from datetime import datetime


@pytest.mark.parametrize("phrase, expected_time", [
    ("3 hours ago",          "7:30 AM"),    # 10:30 - 3h
    ("2 hours ago (edited)", "8:30 AM"),
    ("5 hours ago",          "5:30 AM"),
    ("30 minutes ago",       "10:00 AM"),   # 10:30 - 30m
    ("45 minutes ago (edited)", "9:45 AM"),
    ("10 seconds ago",       "10:29 AM"),
])
def test_relative_time_variants_resolved(phrase, expected_time):
    """All numeric-quantity relative timestamps must resolve to absolute,
    with or without the (edited) suffix."""
    now = datetime(2026, 4, 30, 10, 30)
    raw = (
        f"Mark Escobar {phrase}\n"
        f"Test body.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw, now=now)
    assert "Test body." in out
    assert expected_time in out
    if "(edited)" in phrase:
        assert "(edited)" in out


@pytest.mark.parametrize("phrase", [
    "just now",
    "just now (edited)",
    "yesterday",
    "yesterday (edited)",
])
def test_relative_time_special_phrases_with_edited(phrase):
    """'just now' / 'yesterday' both work with or without (edited)."""
    now = datetime(2026, 4, 30, 10, 30)
    raw = (
        f"Mark Escobar {phrase}\n"
        f"Note text.\n"
        "•\nReply\n•\nAdd link as attachment"
    )
    out = clean_trello_paste(raw, now=now)
    assert "Note text." in out
    # Either an absolute time (just now / today) or yesterday's date
    # should be in the output — i.e., the phrase got rewritten.
    assert phrase not in out  # original wording replaced
    if "(edited)" in phrase:
        assert "(edited)" in out
