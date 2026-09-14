"""Read-only reconciliation for exported Hub identities and L OPS imports.

Use stable IDs and explicit scope mappings only. No names or fuzzy matches.
The summary is safe to track in Git; input exports may contain private data.
"""
from collections import Counter


def reconcile(source, imported, *, source_project, scope_map):
    source_ids = [r["job_id"] for r in source]
    imports = [r for r in imported if r["source_project"] == source_project]
    counts = Counter(r["source_id"] for r in imports)
    index = {r["source_id"]: r for r in imports}
    matched = missing = scope_conflicts = unknown_scope = 0
    missing_by_scope = Counter()
    for row in source:
        target = index.get(row["job_id"])
        scope = row.get("department") or "unknown"
        if target is None or not target.get("target_exists"):
            missing += 1
            missing_by_scope[scope] += 1
        else:
            matched += 1
            expected = scope_map.get(scope)
            if expected is None:
                unknown_scope += 1
            elif target["organization"] != expected:
                scope_conflicts += 1
    source_set = set(source_ids)
    orphans = sum(r["source_id"] not in source_set for r in imports)
    duplicates = sum(n - 1 for n in counts.values() if n > 1)
    duplicate_source = len(source_ids) - len(set(source_ids))
    return {
        "source_count": len(source), "imported_count": len(imports),
        "matched": matched, "missing": missing,
        "missing_by_scope": dict(sorted(missing_by_scope.items())),
        "orphan_imports": orphans, "duplicate_imports": duplicates,
        "duplicate_source_ids": duplicate_source,
        "scope_conflicts": scope_conflicts,
        "matched_without_verified_scope": unknown_scope,
        "identity_cutover_ready": bool(source) and not any((
            missing, orphans, duplicates, duplicate_source, scope_conflicts, unknown_scope)),
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--imports", type=Path, required=True)
    parser.add_argument("--source-project", required=True)
    parser.add_argument("--scope", action="append", required=True, help="Department=Organization; repeat for each scope")
    args = parser.parse_args()
    result = reconcile(json.loads(args.source.read_text(encoding="utf-8")),
                       json.loads(args.imports.read_text(encoding="utf-8")),
                       source_project=args.source_project,
                       scope_map=dict(item.split("=", 1) for item in args.scope))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["identity_cutover_ready"] else 2)
