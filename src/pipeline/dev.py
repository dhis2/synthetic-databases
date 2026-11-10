"""Whether dev is out of date, for `pipeline dev --if-changed`.

The published dev stays as it is unless something that made it changed:

* no dev is published yet
* the pipeline is at another commit, which may change the data, dev's fix-ups, the upgrade or the
  check: dbgen builds the same 43 from the same commit
* DHIS2 master changed its migrations: a commit of dhis2-core between the revision dev was
  migrated by and core-dev:latest's touched the migration module

Only migrations change the database DHIS2 starts on. A core-dev:latest without new ones starts on
the published dev without migrating, so an upgrade would publish the same database again: a new
object version in the bucket, and a rebuild of the image on core's perf runner, for nothing.
"""

import os
from collections.abc import Callable

import httpx

from pipeline import fetch, provenance, stack
from pipeline.config import Database, Version
from pipeline.errors import CheckFailed

CORE = "dhis2/dhis2-core"
# Flyway's migrations of DHIS2, SQL and Java, and the code that runs them.
MIGRATIONS = "dhis-2/dhis-support/dhis-support-db-migration/src/main"


def changes(database: Database, version: Version) -> list[str]:
    """Why an unpinned version needs upgrading again; empty if the published one is current."""
    assert version.dhis2 is not None
    published = fetch.published(database, version.name)
    revision = stack.remote_labels(version.dhis2).get("DHIS2_BUILD_REVISION")
    return reasons(published, provenance.state()["commit"], revision, latest_migration_commit)


def reasons(
    published: dict | None,
    commit: str | None,
    revision: str | None,
    latest_migration_commit: Callable[[str], str | None],
) -> list[str]:
    """Why a published unpinned version is out of date: no longer of this pipeline commit, or of
    DHIS2's migrations at revision. latest_migration_commit gives the last commit of dhis2-core
    that touched the migrations, as of a revision."""
    if published is None:
        return ["none is published"]
    step = published["chain"][-1]
    found = []
    if commit is None or step.get("pipeline") != commit:
        made_by = _short(step.get("pipeline"))
        found.append(f"the pipeline is at {_short(commit)}, it was made by {made_by}")
    migrated = published.get("dhis2", {}).get("DHIS2_BUILD_REVISION")
    if revision is None or migrated is None:
        found.append("DHIS2's revision is unknown, of the image or of the published one")
    elif revision != migrated and latest_migration_commit(revision) != latest_migration_commit(
        migrated
    ):
        found.append(f"DHIS2 changed its migrations between {migrated[:7]} and {revision[:7]}")
    return found


def latest_migration_commit(revision: str) -> str | None:
    """The last commit of dhis2-core touching its migrations, as of revision, from GitHub's API.
    With GITHUB_TOKEN set, as in a workflow, the requests count against its higher rate limit."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.get(
        f"https://api.github.com/repos/{CORE}/commits",
        params={"sha": revision, "path": MIGRATIONS, "per_page": 1},
        headers=headers,
        timeout=60,
    )
    if response.status_code != 200:
        raise CheckFailed(
            f"GitHub answered {response.status_code} for the migrations of {CORE} at "
            f"{revision}: {response.text[:200]}"
        )
    commits = response.json()
    return commits[0]["sha"] if commits else None


def _short(commit: str | None) -> str:
    return commit[:7] if commit else "an unknown commit"
