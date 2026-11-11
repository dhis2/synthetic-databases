"""`pipeline publish`: upload the dumps and manifests of versions to the bucket.

Every version or none: it uploads only once each version's dump matches its manifest, passed
its check, holds the release area and was made by this commit of the pipeline, from a clean
tree. A release's versions are made from a tag; an unpinned one, dev, from any commit; a release
candidate from any commit too, each version published as rc-<version>, never under a release's
name, so core's harness runs it as DB_VERSION=rc-43.

Each dump carries in its metadata what a HEAD request on it tells without downloading it
(metadata()); its manifest.json beside it carries none, as it holds all of it. Writes take
credentials allowed s3:PutObject under the type's folder, from the environment, as the aws CLI
takes them.
"""

import json
import os
import subprocess
import sys
from collections.abc import Mapping

from pipeline import manifest, provenance
from pipeline.config import BUCKET, Database, lock
from pipeline.errors import CheckFailed, UsageError

REPOSITORY = "dhis2/synthetic-databases"
# The prefix of a release candidate's versions in the bucket, such as rc-43: a prefix rather than
# a suffix, so candidates list apart from releases, and a lifecycle rule on perfland-mnch/rc- could
# expire them.
CANDIDATE = "rc-"


def run(
    database: Database,
    names: list[str],
    dry_run: bool,
    candidate: bool = False,
    bucket: str = BUCKET,
) -> None:
    versions = [lock().version(n) for n in names]
    state = provenance.state()
    problems = []
    records = {}
    for version in versions:
        name = version.name
        try:
            record = manifest.read(database, name)
            manifest.check_dump(database, name, record)
        except (UsageError, CheckFailed) as e:
            problems.append(f"{name}: {e}")
            continue
        records[name] = record
        checks = record.get("checks")
        if not checks:
            problems.append(f"{name}: not checked, run pipeline check {database.name} {name}")
        elif not checks["ok"]:
            problems.append(f"{name}: its check failed: {'; '.join(checks['problems'])}")
        if record["area"]["orgunit"] != database.orgunit:
            problems.append(
                f"{name}: holds {record['area']['orgunit']}, publish.toml's area is "
                f"{database.orgunit}"
            )
        step = record["chain"][-1]
        if step["pipeline"] != state["commit"]:
            problems.append(
                f"{name}: made by commit {step['pipeline']}, the tree is at {state['commit']}"
            )
        if record["pipeline"]["dirty"] is not False:
            problems.append(f"{name}: made from a tree with uncommitted changes")
    if state["dirty"] is not False:
        problems.append("the tree has uncommitted changes")
    if problem := tag_problem(all(v.unpinned for v in versions), state["tag"], candidate):
        problems.append(problem)

    if problems:
        message = "will not publish:\n  " + "\n  ".join(problems)
        if not dry_run:
            raise UsageError(message)
        print(f"publish: dry run, would refuse: {message}", file=sys.stderr)

    label = state["tag"] or state["commit"] or "unknown"
    for name, record in records.items():
        published = published_name(name, candidate)
        uploads = [
            (database.dump(name), database.dump_name, "application/gzip", metadata(record, label)),
            (database.manifest(name), "manifest.json", "application/json", {}),
        ]
        for path, file, content_type, fields in uploads:
            command = [
                "aws",
                "s3",
                "cp",
                str(path),
                f"s3://{bucket}/{database.key(published, file)}",
                "--content-type",
                content_type,
                *(["--metadata", json.dumps(fields)] if fields else []),
                "--only-show-errors",
            ]
            print(f"publish: {' '.join(command)}", file=sys.stderr)
            if dry_run:
                continue
            try:
                result = subprocess.run(command)
            except FileNotFoundError as e:
                raise UsageError("the aws CLI is not installed, or not on PATH") from e
            if result.returncode != 0:
                raise CheckFailed(f"uploading {path} failed, its error is above")
    if not dry_run:
        published = ", ".join(published_name(n, candidate) for n in records)
        print(f"publish: {published} to s3://{bucket}/{database.type}/", file=sys.stderr)


def published_name(name: str, candidate: bool) -> str:
    """The version's folder in the bucket: rc-43 for a candidate of 43."""
    return CANDIDATE + name if candidate else name


def tag_problem(unpinned: bool, tag: str | None, candidate: bool) -> str | None:
    """Why the versions can't be published from this commit: a release's need a tag at HEAD,
    unpinned ones and a candidate's don't."""
    if unpinned or candidate or tag:
        return None
    return "a release publishes from a tag, and no tag points at HEAD; --candidate publishes rc-"


def metadata(record: dict, label: str, env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """The S3 metadata of a version's dump, from its manifest: who saved it and in which run, the
    DHIS2 and Flyway schema it is at, its sha256, area and Postgres. saved_by is Sierra Leone's
    dumps' name; dhis2_version and dhis2_revision are DHIS2's /api/system/info's. A field without
    a value is left out."""
    fields = {
        "saved_by": f"{REPOSITORY}@{label}",
        "run_url": run_url(env),
        "dhis2_version": record["dhis2"].get("DHIS2_VERSION"),
        "dhis2_revision": record["dhis2"].get("DHIS2_BUILD_REVISION"),
        "flyway_schema_version": record["chain"][-1].get("flyway_version"),
        "sha256": record["dump"]["sha256"],
        "orgunit_code": record["area"]["orgunit"],
        "postgres_image": record["images"]["postgres"],
    }
    return {k: v for k, v in fields.items() if v}


def run_url(env: Mapping[str, str]) -> str | None:
    """The attempt of the GitHub Actions run that publishes, None outside of one. dev.yml
    publishes dev from the same commit run after run: the run tells them apart, and links to its
    logs and manifests."""
    run = env.get("GITHUB_RUN_ID")
    if not run:
        return None
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repository = env.get("GITHUB_REPOSITORY", REPOSITORY)
    attempt = env.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{server}/{repository}/actions/runs/{run}/attempts/{attempt}"
