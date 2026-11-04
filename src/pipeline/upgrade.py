"""`pipeline upgrade`: a version's dump from the dump of the version it upgrades from.

1. Restore the source's dump into an empty database (stack.py).
2. Run upgrades/<version>/check.sql, the migration notes' queries, failing on any row, then
   pre.sql.
3. Start the version's DHIS2 and wait until it answers /api/ping: Flyway has migrated.
4. Stop DHIS2, run post.sql, and record the rows Flyway added to flyway_schema_history, with
   their execution_time and success.
5. pg_dump the database as plain SQL, gzipped, and write the manifest, the source's with this
   step added to its chain.
"""

import sys

import psycopg

from pipeline import manifest, provenance, sqlfile, stack
from pipeline.config import Database, check_fixups, dhis2_version_fits, lock
from pipeline.errors import CheckFailed, UsageError

# Rows a failing check prints of what it found.
SHOWN_ROWS = 5


def run(database: Database, name: str, timeout: int) -> dict:
    version = lock().version(name)
    if version.source is None or version.dhis2 is None:
        raise UsageError(f"{name} is the base, which pipeline build makes")
    check_fixups(version)
    source = manifest.read(database, version.source)
    source_dump = manifest.check_dump(database, version.source, source)
    image = stack.image_ref(version.dhis2)
    labels = stack.labels(image)
    if not dhis2_version_fits(name, labels.get("DHIS2_VERSION", "")):
        raise UsageError(
            f"lock.toml pins {image} for {name}, but it is DHIS2 {labels.get('DHIS2_VERSION')}"
        )
    fixups = {f: version.upgrades / f for f in ("check.sql", "pre.sql", "post.sql")}
    log = database.logs(name) / "upgrade.log"
    target = database.dump(name)
    # A failure from here on leaves no dump or manifest of this version rather than old ones.
    database.manifest(name).unlink(missing_ok=True)
    target.unlink(missing_ok=True)

    print(
        f"upgrade: {version.source} to {name}, DHIS2 {labels.get('DHIS2_VERSION')}", file=sys.stderr
    )
    with stack.database(source_dump) as restore_seconds:
        with stack.connect(autocommit=True) as pg:
            before = last_rank(pg)
            run_checks(pg, fixups["check.sql"])
            run_script(pg, fixups["pre.sql"])
        start_seconds = stack.start_dhis2(image, timeout, log)
        stack.stop_dhis2(image, log)
        with stack.connect(autocommit=True) as pg:
            run_script(pg, fixups["post.sql"])
            migrations = flyway_rows(pg, after=before)
        failed = [m["script"] for m in migrations if not m["success"]]
        if failed:
            raise CheckFailed(f"Flyway recorded failed migrations: {', '.join(failed)}")
        sha256, size, dump_seconds = stack.dump(target)

    state = provenance.state()
    step = {
        "version": name,
        "from": version.source,
        "image": image,
        "dhis2": labels.get("DHIS2_VERSION"),
        "pipeline": state["commit"],
        "fixups": {f: sqlfile.describe(path) for f, path in fixups.items()},
        "flyway_version": migrations[-1]["version"]
        if migrations
        else source["chain"][-1].get("flyway_version"),
        "migrations": migrations,
        "seconds": {"restore": restore_seconds, "start": start_seconds, "dump": dump_seconds},
    }
    record = {
        **source,
        "version": name,
        "dump": {"file": target.name, "sha256": sha256, "bytes": size},
        "dhis2": labels,
        "pipeline": state,
        "images": {"dhis2": image, "postgres": lock().images["postgres"]},
        "chain": [*source["chain"], step],
        "checks": None,
    }
    manifest.write(database, name, record)
    slowest = sorted(migrations, key=lambda m: -m["execution_ms"])[:5]
    print(
        f"upgrade: {name} done, {len(migrations)} migrations in {start_seconds} s of start, "
        f"slowest: "
        + ", ".join(f"{m['version']} {m['execution_ms'] / 1000:.1f}s" for m in slowest),
        file=sys.stderr,
    )
    return record


def last_rank(pg: psycopg.Connection) -> int:
    with pg.cursor() as cur:
        cur.execute("select coalesce(max(installed_rank), 0) from flyway_schema_history")
        row = cur.fetchone()
        assert row is not None
        return row[0]


def flyway_rows(pg: psycopg.Connection, after: int = 0) -> list[dict]:
    """The rows of flyway_schema_history after installed_rank `after`, in order."""
    with pg.cursor() as cur:
        cur.execute(
            """
            select installed_rank, version, description, type, script, execution_time, success
            from flyway_schema_history
            where installed_rank > %s
            order by installed_rank
            """,
            [after],
        )
        return [
            {
                "rank": rank,
                "version": version,
                "description": description,
                "type": kind,
                "script": script,
                "execution_ms": ms,
                "success": success,
            }
            for rank, version, description, kind, script, ms, success in cur.fetchall()
        ]


def run_checks(pg: psycopg.Connection, path) -> None:
    """Run each query of a check.sql in a read-only transaction; fail naming those that return
    rows, and the first of their rows."""
    found = []
    with pg.transaction(), pg.cursor() as cur:
        cur.execute("set transaction read only")
        for statement in sqlfile.statements(path.read_text()):
            where = f"{path.parent.name}/{path.name}:{statement.line}"
            try:
                cur.execute(statement.sql.encode())
            except psycopg.Error as e:
                raise CheckFailed(f"{where} failed: {e}") from e
            if cur.description is None:
                raise UsageError(f"{where}: a check is a query, which writes nothing")
            rows = cur.fetchmany(SHOWN_ROWS + 1)
            if rows:
                more = " and more" if len(rows) > SHOWN_ROWS else ""
                found.append(f"{where} {statement.title}: {rows[:SHOWN_ROWS]}{more}")
            print(f"check: {where} {statement.title}: {len(rows)} rows", file=sys.stderr)
    if found:
        raise CheckFailed(
            "the migration notes' checks found rows the upgrade fails on or changes; fix them "
            "with a fix-up in pre.sql:\n  " + "\n  ".join(found)
        )


def run_script(pg: psycopg.Connection, path) -> None:
    """Run a pre.sql or post.sql, if it holds a statement, in one transaction."""
    statements = sqlfile.statements(path.read_text())
    if not statements:
        return
    print(f"fix-up: {path.parent.name}/{path.name}, {len(statements)} statements", file=sys.stderr)
    with pg.transaction(), pg.cursor() as cur:
        for statement in statements:
            try:
                cur.execute(statement.sql.encode())
            except psycopg.Error as e:
                where = f"{path.parent.name}/{path.name}:{statement.line}"
                raise CheckFailed(f"{where} failed: {e}") from e
