"""Print privacy-safe aggregate coverage for the local job index."""

from __future__ import annotations

import argparse
import json
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    args = parser.parse_args()

    with sqlite3.connect(args.database) as connection:
        departments = [
            {"department": row[0], "count": row[1]}
            for row in connection.execute(
                "select department, count(*) from jobs "
                "group by department order by department"
            )
        ]
        total, unknown = connection.execute(
            "select count(*), sum(case when department is null "
            "or trim(department) = '' then 1 else 0 end) from jobs"
        ).fetchone()
        folder_links = connection.execute(
            "select count(*) from job_links where link_type = 'folder'"
        ).fetchone()[0]

    print(json.dumps({
        "departments": departments,
        "total": total,
        "unknown": unknown,
        "folder_links": folder_links,
    }))


if __name__ == "__main__":
    main()
