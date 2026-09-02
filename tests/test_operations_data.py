from operations_data import OperationsData


class FakeDb:
    def __init__(self):
        self.jobs = [{
            "job_id": "job-aperto", "canon_key": "aperto property management",
            "display_name": "Aperto Property Management - (Tres Lagos - Unit 3208)",
            "department": "IE", "lifecycle_stage": "active",
            "claim_number": "CLM-100", "carrier": "AAA",
            "date_received": "2026-08-13",
        }, {
            "job_id": "job-rose", "canon_key": "rose, jasmin",
            "display_name": "Rose, Jasmin", "department": "IE",
            "lifecycle_stage": "monitoring", "carrier": "State Farm",
        }]
        self.children = [{
            "id": 7, "parent_canon": "aperto property management",
            "name": "Tres Lagos - Unit 3208 - 8.13.26", "kind": "unit",
            "trello_card": "child-card", "folder_path": "",
            "property": "Tres Lagos", "unit": "3208", "claim_date": "8.13.26",
        }]

    def backend_name(self):
        return "supabase"

    def iter_jobs(self):
        return self.jobs

    def all_children(self):
        return self.children

    def all_aliases(self):
        return [{"alias": "Jasmin Rose", "canon_key": "rose, jasmin"}]

    def list_job_log_entries(self, canon):
        return [{"entry_id": "log-1", "work_type": "Monitor",
                 "canon": canon}]


class FakeSupabase:
    def __init__(self, *, signed_in=True, v11=False):
        self.signed_in = signed_in
        self.v11 = v11

    def health(self):
        return {"configured": True, "reachable": True,
                "signed_in": self.signed_in,
                "user": {"email": "nathan@servpro10100.com"} if self.signed_in else None,
                "error": "Sign in again" if not self.signed_in else ""}

    def rest(self, method, table, *, params=None, **_kwargs):
        assert method == "GET"
        rows = {
            "crm_job_departments": [
                {"job_id": "job-aperto", "work_environment": "EMS",
                 "stage": "mitigation"},
                {"job_id": "job-aperto", "work_environment": "Recon",
                 "stage": "planning"},
                {"job_id": "job-rose", "work_environment": "Contents",
                 "stage": "pack_out"},
            ],
            "crm_job_log_entries": [] if self.v11 else None,
            "crm_clients": ([{
                "client_id": "client-1", "display_name": "Jasmin Rose",
                "department": "IE", "phone": "555-0100", "email": "",
                "address_json": {},
            }] if self.v11 else None),
            "crm_claims": ([{
                "claim_id": "claim-1", "client_id": "client-1",
                "claim_number": "SF-1", "carrier": "State Farm",
                "status": "open", "date_received": "2026-08-25",
            }] if self.v11 else None),
        }.get(table)
        if rows is None:
            raise RuntimeError(f"HTTP 404 PGRST205 Could not find the table {table}")
        offset = int((params or {}).get("offset") or 0)
        limit = int((params or {}).get("limit") or 1000)
        return rows[offset:offset + limit]


def test_v9_shared_index_drives_clients_jobs_and_divisions():
    data = OperationsData(FakeDb(), FakeSupabase(), ttl=60)
    snapshot = data.snapshot()

    assert snapshot["ok"] is True
    assert snapshot["state"]["source"] == "supabase"
    assert snapshot["state"]["client_model"] == "job_index_v9"
    aperto = next(row for row in snapshot["clients"]
                  if row["name"] == "Aperto Property Management")
    assert aperto["job_count"] == 1
    assert aperto["divisions"] == ["EMS", "RECON"]
    assert any("Client/claim tables" in warning for warning in snapshot["warnings"])


def test_pipeline_card_is_linked_to_shared_parent_by_child_trello_id():
    data = OperationsData(FakeDb(), FakeSupabase())
    jobs = data.enrich_jobs([{
        "card_id": "child-card", "client": "A Trello title",
        "division": "EMS", "divisions": ["EMS"],
    }])

    assert jobs[0]["identity_state"] == "linked"
    assert jobs[0]["job_id"] == "job-aperto"
    assert jobs[0]["account_client"] == "Aperto Property Management"
    assert jobs[0]["job_name"] == "Tres Lagos - Unit 3208 - 8.13.26"
    assert jobs[0]["carrier"] == "AAA"


def test_child_or_alias_reference_opens_the_shared_client_account():
    data = OperationsData(FakeDb(), FakeSupabase())
    child = data.account("Tres Lagos - Unit 3208 - 8.13.26")
    alias = data.account("Jasmin Rose")

    assert child["client"]["name"] == "Aperto Property Management"
    assert child["jobs"][0]["unit"] == "3208"
    assert child["job_log"][0]["canon"] == "aperto property management"
    assert alias["client"]["name"] == "Rose, Jasmin"


def test_invalid_session_is_reported_instead_of_masquerading_as_local_data():
    data = OperationsData(FakeDb(), FakeSupabase(signed_in=False))
    snapshot = data.snapshot()

    assert snapshot["ok"] is False
    assert snapshot["state"]["mode"] == "auth_required"
    assert snapshot["state"]["source"] == "supabase"
    assert snapshot["clients"] == []


def test_v11_client_and_claim_rows_take_over_when_installed():
    db = FakeDb()
    db.jobs[1].update({"client_id": "client-1", "claim_id": "claim-1"})
    data = OperationsData(db, FakeSupabase(v11=True))
    account = data.account("Jasmin Rose")

    assert account["data_state"]["client_model"] == "crm_v11"
    assert account["client"]["name"] == "Jasmin Rose"
    assert account["client"]["phone"] == "555-0100"
    assert account["jobs"][0]["claim_number"] == "SF-1"
    assert account["jobs"][0]["carrier"] == "State Farm"
