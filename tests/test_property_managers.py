import ems_db
import ems_db_sqlite
import property_managers as pm


def setup_function(_):
    ems_db.use_backend("sqlite")


def test_directory_seeds_and_edits(tmp_path):
    ems_db_sqlite.reset_db_path(str(tmp_path / "pm.sqlite3"))
    rows = pm.list_records()
    assert len(rows) == 10
    aperto = next(r for r in rows if r["company_name"] ==
                  "Aperto Property Management")
    aperto["contact_name"] = "New Manager"
    saved, old = pm.save_record(aperto)
    assert saved["contact_name"] == "New Manager"
    assert old["company_name"] == "Aperto Property Management"
    assert next(r for r in pm.list_records()
                if r["company_name"] == "Aperto Property Management")[
                    "contact_name"] == "New Manager"


def test_company_rename_keeps_child_records(tmp_path):
    ems_db_sqlite.reset_db_path(str(tmp_path / "rename.sqlite3"))
    record = next(r for r in pm.list_records()
                  if r["company_name"] == "PCM")
    ems_db.set_child(record["id"], "Palm Court - Unit 4", kind="unit")
    record["company_name"] = "PCM Management"
    saved, _ = pm.save_record(record)
    assert saved["id"] == "pcm management"
    assert [c["name"] for c in ems_db.children_of(saved["id"])] == [
        "Palm Court - Unit 4"]
