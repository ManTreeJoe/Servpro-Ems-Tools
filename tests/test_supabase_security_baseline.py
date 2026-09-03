from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "supabase" / "013_rls_security_baseline.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_privileged_functions_are_not_callable_before_sign_in():
    sql = _sql()
    for function in (
        "admin_list_user_access()",
        "admin_set_user_departments(uuid, text[])",
        "is_app_admin()",
        "my_app_access()",
        "my_departments()",
        "rls_auto_enable()",
    ):
        assert f"revoke execute on function public.{function} from public, anon" in sql


def test_read_only_identity_helpers_do_not_need_definer_privileges():
    sql = _sql()
    for function in ("my_departments", "is_app_admin", "my_app_access"):
        start = sql.index(f"function public.{function}")
        end = sql.index("$$;", start)
        section = sql[start:end]
        assert "security invoker" in section
        assert "set search_path = ''" in section


def test_future_functions_are_not_executable_by_public_or_anon():
    sql = _sql()
    assert "alter default privileges in schema public revoke execute on functions from public" in sql
    assert "alter default privileges in schema public revoke execute on functions from anon" in sql


def test_own_row_policies_cache_auth_uid_once_per_statement():
    sql = _sql()
    assert "using (user_id = (select auth.uid()))" in sql
    assert sql.count("using (user_id = (select auth.uid()))") >= 2


def test_related_job_foreign_key_has_a_covering_index():
    assert "crm_job_relationships (related_job_id)" in _sql()
