"""ems_db.resolve_and_link — auto-linking so tools stop mismatching.

The core streamlining rule: when two different name spellings both point at
the same strong identifier (OD folder / Trello card / CompanyCam project),
they're provably the same job, so the new spelling is recorded as an alias
and every tool then resolves it to the one canonical job."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ems_db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    ems_db.reset_db_path(str(tmp_path / "test.db"))
    yield


def test_shared_folder_teaches_alias():
    folder = r"X:\IE_Public\2026 Jobs\Bromme Ira\EMS"
    # Tool 1 sets up the job under one spelling + its folder.
    j1 = ems_db.resolve_and_link("Bromme Ira", folder_path=folder,
                                 create=True)
    assert j1 and j1["canon_key"] == ems_db.canon_key("Bromme Ira")

    # Tool 2 hits the SAME folder but with a different spelling → same job,
    # and "Ira Bromme" is now a learned alias.
    j2 = ems_db.resolve_and_link("Ira Bromme", folder_path=folder)
    assert j2["canon_key"] == j1["canon_key"]
    # The new spelling now resolves on its own, no folder hint needed.
    assert ems_db.find_job_by_name("Ira Bromme")["canon_key"] == j1["canon_key"]


def test_folder_path_normalized_across_slash_and_case():
    a = r"X:\IE_Public\2026 Jobs\Smith John\EMS"
    b = "x:/ie_public/2026 jobs/smith john/ems"          # slashes + case differ
    ems_db.resolve_and_link("Smith John", folder_path=a, create=True)
    j = ems_db.resolve_and_link("Johnny Smith", folder_path=b)
    assert j["canon_key"] == ems_db.canon_key("Smith John")


def test_trello_url_and_bare_id_match():
    ems_db.resolve_and_link("Club Pilates",
                            trello_card="https://trello.com/c/AbC12345/9-club",
                            create=True)
    j = ems_db.resolve_and_link("Pilates Club", trello_card="AbC12345")
    assert j["canon_key"] == ems_db.canon_key("Club Pilates")


def test_companycam_project_ties_spellings():
    ems_db.resolve_and_link("Bernardo, Foilan", companycam_project="proj_9",
                            create=True)
    j = ems_db.resolve_and_link("Foilan Bernardo", companycam_project="proj_9")
    assert j["canon_key"] == ems_db.canon_key("Bernardo, Foilan")


def test_links_accumulate_on_one_job():
    folder = r"X:\J\Doe Jane"
    ems_db.resolve_and_link("Doe Jane", folder_path=folder, create=True)
    # A later tool identifies the SAME job by its folder (the shared strong
    # link) and adds the Trello + CompanyCam refs it just discovered.
    ems_db.resolve_and_link("Jane Doe", folder_path=folder,
                            trello_card="ZZ99", companycam_project="cc_1")
    key = ems_db.canon_key("Doe Jane")
    assert ems_db.get_link(key, ems_db.LINK_FOLDER)
    assert ems_db.get_link(key, ems_db.LINK_TRELLO) == "zz99"
    assert ems_db.get_link(key, ems_db.LINK_COMPANYCAM) == "cc_1"


def test_no_create_returns_none_when_unknown():
    assert ems_db.resolve_and_link("Nobody Here") is None


def test_does_not_cross_wire_two_real_jobs():
    # Two DISTINCT real jobs already exist.
    ems_db.upsert_job(display_name="Alpha One")
    ems_db.upsert_job(display_name="Beta Two")
    # A stray call naming Beta but pointing at Alpha's folder must NOT alias
    # Beta into Alpha (that would be a silent merge). Alpha still wins the
    # folder; Beta keeps its own identity.
    ems_db.set_link(ems_db.canon_key("Alpha One"), ems_db.LINK_FOLDER,
                    r"X:\shared")
    ems_db.resolve_and_link("Beta Two", folder_path=r"X:\shared")
    # "Beta Two" still resolves to its own job, not Alpha.
    assert ems_db.find_job_by_name("Beta Two")["canon_key"] == \
        ems_db.canon_key("Beta Two")
