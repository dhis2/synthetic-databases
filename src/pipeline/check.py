"""`pipeline check`: a version's dump as a consumer gets it.

Restored into an empty database, the version's DHIS2 must start on it without applying a
migration, as core's harness starts every run from the restored dump. Then:

* every row of flyway_schema_history succeeded
* the tracked entities, enrollments, events (trackerevent and singleevent from 43 on, which
  V2_43_21 split event into), relationships and users number as in dbgen's build
* a clerk's tracker queries answer 200 with records, for each program: the clerk of the org unit
  with the most enrollments in it, with the spec's password

The results go into the manifest's checks, also when they fail, and a failure fails the command.
"""

import sys
import time

import httpx
import psycopg

from pipeline import manifest, stack
from pipeline.config import Database, lock
from pipeline.errors import CheckFailed
from pipeline.upgrade import flyway_rows

# dbgen's tables whose rows a dump keeps through every upgrade, and the users.
COUNTED = ("trackedentity", "enrollment", "event", "relationship", "users")
QUERY_TIMEOUT_SECONDS = 300


def run(database: Database, name: str, timeout: int) -> dict:
    lock().version(name)
    record = manifest.read(database, name)
    dump = manifest.check_dump(database, name, record)
    image = record["images"]["dhis2"]
    built = record["build"]
    expected = {table: built["tables"][table]["rows"] for table in COUNTED}
    users = built["spec"]["users"]
    log = database.logs(name) / "check.log"
    problems = []

    print(f"check: {name}, {image}", file=sys.stderr)
    with stack.database(dump) as restore_seconds:
        with stack.connect(autocommit=True) as pg:
            restored = flyway_rows(pg)
        start_seconds = stack.start_dhis2(image, timeout, log)
        with stack.connect(autocommit=True) as pg:
            migrated = flyway_rows(pg, after=restored[-1]["rank"] if restored else 0)
            counts = count(pg, users["prefix"])
            clerks = {
                p["key"]: clerk(pg, p["uid"], users["prefix"]) for p in built["spec"]["programs"]
            }
        queries = []
        for program in built["spec"]["programs"]:
            username = clerks[program["key"]]
            if username is None:
                problems.append(f"{program['key']}: no clerk of the program's org units")
                continue
            queries += clerk_queries(program, username, users["password"])
        stack.stop_dhis2(image, log)

    failed = [m["script"] for m in restored if not m["success"]]
    if failed:
        problems.append(f"flyway_schema_history holds failed migrations: {', '.join(failed)}")
    if migrated:
        problems.append(
            f"DHIS2 migrated the dump at start, {len(migrated)} migrations: "
            + ", ".join(str(m["version"]) for m in migrated[:10])
        )
    problems += [
        f"{table}: {counts[table]:,} rows, the build has {expected[table]:,}"
        for table in COUNTED
        if counts[table] != expected[table]
    ]
    problems += [
        f"{q['program']} {q['query']} as {q['user']}: {q['status']}, {q['items']} records"
        for q in queries
        if not q["ok"]
    ]
    results = {
        "ok": not problems,
        "problems": problems,
        "dhis2": record["dhis2"].get("DHIS2_VERSION"),
        "flyway": {
            "rows": len(restored),
            "version": restored[-1]["version"] if restored else None,
            "migrated_at_start": migrated,
        },
        "counts": counts,
        "expected": expected,
        "queries": queries,
        "seconds": {"restore": restore_seconds, "start": start_seconds},
    }
    manifest.write(database, name, {**record, "checks": results})
    for q in queries:
        print(
            f"  {q['seconds']:7.3f}s {q['status']} {q['items']:4d} {q['program']} {q['query']}",
            file=sys.stderr,
        )
    if problems:
        raise CheckFailed(
            f"check of {name} found {len(problems)} problems:\n  " + "\n  ".join(problems)
        )
    print(
        f"check: {name} ok, DHIS2 up in {start_seconds} s without a migration, "
        + ", ".join(f"{t} {n:,}" for t, n in counts.items()),
        file=sys.stderr,
    )
    return results


def count(pg: psycopg.Connection, prefix: str) -> dict[str, int]:
    with pg.cursor() as cur:

        def one(query: str, params: list | None = None) -> int:
            cur.execute(query.encode(), params)
            row = cur.fetchone()
            assert row is not None
            return row[0]

        split = one("select to_regclass('public.trackerevent') is not null")
        events = (
            one("select (select count(*) from trackerevent) + (select count(*) from singleevent)")
            if split
            else one("select count(*) from event")
        )
        return {
            "trackedentity": one("select count(*) from trackedentity"),
            "enrollment": one("select count(*) from enrollment"),
            "event": events,
            "relationship": one("select count(*) from relationship"),
            "users": one("select count(*) from userinfo where username like %s", [f"{prefix}.%"]),
        }


def clerk(pg: psycopg.Connection, program: str, prefix: str) -> str | None:
    """The clerk of the org unit with the most enrollments in the program."""
    with pg.cursor() as cur:
        cur.execute(
            """
            select u.username
            from enrollment en
            join program p on p.programid = en.programid
            join usermembership m on m.organisationunitid = en.organisationunitid
            join userinfo u on u.userinfoid = m.userinfoid
            where p.uid = %s and u.username like %s
            group by u.username
            order by count(*) desc, u.username
            limit 1
            """,
            [program, f"{prefix}.%"],
        )
        row = cur.fetchone()
        return row[0] if row else None


def clerk_queries(program: dict, username: str, password: str) -> list[dict]:
    """A clerk's tracker queries, as core's TrackerTest makes them, each must answer 200 with
    records."""
    uid = program["uid"]
    queries = [
        (
            "tracked entities CAPTURE",
            "/api/tracker/trackedEntities",
            {"program": uid, "orgUnitMode": "CAPTURE", "pageSize": 15},
        ),
        (
            "enrollments CAPTURE",
            "/api/tracker/enrollments",
            {"program": uid, "orgUnitMode": "CAPTURE", "pageSize": 15},
        ),
        (
            "events by occurredAt",
            "/api/tracker/events",
            {"program": uid, "pageSize": 50, "order": "occurredAt:desc"},
        ),
    ]
    out = []
    with httpx.Client(
        base_url=stack.BASE_URL, auth=(username, password), timeout=QUERY_TIMEOUT_SECONDS
    ) as http:
        for name, path, params in queries:
            start = time.perf_counter()
            response = http.get(path, params=params)
            seconds = round(time.perf_counter() - start, 3)
            body = response.json() if response.status_code == 200 and response.content else {}
            items = next((v for v in body.values() if isinstance(v, list)), []) if body else []
            out.append(
                {
                    "program": program["key"],
                    "query": name,
                    "path": path,
                    "params": params,
                    "user": username,
                    "status": response.status_code,
                    "items": len(items),
                    "seconds": seconds,
                    "ok": response.status_code == 200 and len(items) > 0,
                }
            )
    return out
