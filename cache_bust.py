"""One place that drops every process-lifetime cache.

Two things invalidate the world: switching department, and saving Settings.
Both used to be handled ad hoc — the department switch had its own list in
home_web, and Settings had nothing at all, which is why a settings change
needed an app restart to take effect.

Every cache here exists because some module resolved a config-derived value
once and kept it: a Trello board id looked up BY NAME in the active
workspace, the department→folder-root map, the chosen storage backend. None
of them notice config.json changing underneath, since `config.load()` is
mtime-cached but their derived values are not.

Import everything lazily and swallow everything. A missing or broken module
must never block a settings save or a department switch — the worst case
for a failed invalidation is stale data, and the worst case for raising
here is the user can't change their settings at all.
"""

# (module_name, attribute) pairs — each a no-arg invalidator.
#
# Everything here is keyed by NAME or by nothing at all, so an entry made
# under one department is indistinguishable from one made under the other.
# These must always be dropped.
_INVALIDATORS = (
    # Trello board / list / member ids, all resolved by NAME in the active
    # workspace. Stale ones serve the other department's boards.
    ("trello_client",   "invalidate_caches"),
    ("weekly_checkins", "invalidate_caches"),      # own Estimating-board id
    # department → audit_base root map, used to stamp jobs.department
    ("ems_db",          "invalidate_department_cache"),
    # which storage backend is live (sqlite / supabase)
    ("ems_db",          "invalidate_backend"),
    # CompanyCam photo tags — cheap to refetch, and the token may have changed
    ("companycam_api",  "invalidate_tag_cache"),
    # type-ahead index (job names + aliases) built from the job index, so a
    # backend switch or a department change must rebuild it
    ("job_search",      "invalidate_cache"),
)

# Caches keyed by ABSOLUTE PATH. IE and OC resolve to entirely different
# roots (X:\IE_Public vs the OC OneDrive) for both audit_base and runs_dir,
# so a key made under one department can never be read back under the
# other — the path itself is the separator. Dropping these on a department
# switch therefore protects nothing and costs a full re-scan of the network
# share, which is the expensive part of coming back to a franchise.
#
# They ARE still dropped on a settings save, where the roots themselves can
# change under a key that stays the same shape.
_PATH_KEYED_INVALIDATORS = (
    # per-year folder listing, keyed off the year-folder path (5-min TTL)
    ("audit_logic",     "invalidate_year_index_cache"),
)


def invalidate_all(reason: str = "", *, keep_path_keyed: bool = False) -> dict:
    """Drop every derived cache. Returns {cleared: [...], failed: [...]}.

    `keep_path_keyed` spares the path-keyed caches above — set by the
    department switch, which cannot be served a stale entry from the other
    franchise because their roots differ.
    """
    cleared, failed = [], []
    todo = list(_INVALIDATORS)
    if not keep_path_keyed:
        todo += list(_PATH_KEYED_INVALIDATORS)
    for mod_name, fn_name in todo:
        try:
            mod = __import__(mod_name)
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                fn()
                cleared.append(f"{mod_name}.{fn_name}")
        except Exception as ex:
            failed.append(f"{mod_name}.{fn_name}: {type(ex).__name__}")
    # state_hub caches parsed run-docs; it has no invalidator of its own.
    # Keyed by ("parse_run_doc", normalised path) and mtime-checked on read,
    # so it is path-keyed twice over — spared for the same reason.
    if not keep_path_keyed:
        try:
            from state_hub import hub as _hub
            _hub._cache.clear()
            cleared.append("state_hub")
        except Exception as ex:
            failed.append(f"state_hub: {type(ex).__name__}")
    # config itself is mtime-cached, but a save within the same second can
    # land on an unchanged mtime, so force the next read to re-parse.
    try:
        import config
        config._CACHE = None
        config._CACHE_MTIME = None
        cleared.append("config")
    except Exception as ex:
        failed.append(f"config: {type(ex).__name__}")
    if reason:
        try:
            import ems_log
            ems_log.info("cache", f"invalidated ({reason}): "
                                  f"{len(cleared)} ok, {len(failed)} failed")
        except Exception:
            pass
    return {"cleared": cleared, "failed": failed}
