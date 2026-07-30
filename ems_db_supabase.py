"""Job index — shared Postgres backend, over Supabase's PostgREST API.

NOT IMPLEMENTED YET. This module exists so the backend switch in `ems_db`
is real and testable before the implementation lands: selecting it fails
loudly with an actionable message instead of silently falling back.

Design (see project_supabase_backend):
  * HTTPS + `urllib` only — same shape as trello_client / companycam_api.
    No psycopg, no new dependency, nothing added to the PyInstaller build.
  * Auth is a per-user session (email OTP), NOT a database password. The
    publishable key identifies the project and grants nothing on its own;
    Row-Level Security decides what each signed-in user can see, so the
    key is safe inside a shipped .exe.
  * IE/OC separation is enforced by RLS on `jobs.department` plus the
    `app_user_departments` membership table — not by client code.
  * Must satisfy the same ~40 functions `ems_db_sqlite` exposes. The
    existing ems_db test suite is run against BOTH backends; that
    conformance run is what proves this implementation correct.
"""

_MESSAGE = (
    "The Supabase backend is not implemented yet. Set ems_db_backend to "
    "'sqlite' in config.json (or remove the key) to use the local index."
)


def __getattr__(name):
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    raise NotImplementedError(f"{_MESSAGE} (tried to call ems_db.{name})")
