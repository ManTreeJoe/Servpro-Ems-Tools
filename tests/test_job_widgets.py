"""Tests for the shared client-card helpers."""
from datetime import datetime

from job_widgets import extract_job_year


def test_extract_year_from_year_jobs_path():
    assert extract_job_year(r"X:\IE_Public\2026 Jobs\Smith, John") == 2026


def test_extract_year_with_trailing_slash():
    assert extract_job_year(r"X:\IE_Public\2025 Jobs\Doe, Jane\\") in (2025,
        datetime.today().year)


def test_extract_year_no_year_in_parent_falls_back_to_today():
    # No 4-digit run anywhere in the path → today's year
    assert extract_job_year(r"X:\IE_Public\Some Folder\Client") == \
        datetime.today().year


def test_extract_year_none_path():
    assert extract_job_year(None) == datetime.today().year


def test_extract_year_empty_string():
    assert extract_job_year("") == datetime.today().year


def test_extract_year_picks_first_match():
    # Sanity — when the parent name has multiple digit runs, the regex
    # grabs the first 4-digit run (which is what we want for year).
    assert extract_job_year(r"X:\Root\2024 Q3 Jobs 12\client") == 2024
