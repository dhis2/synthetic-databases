"""`pipeline publish`: upload the dumps and manifests of versions to the bucket.

Every version or none: it uploads only once each version's dump matches its manifest, passed
its check, holds the release area and was made by this commit of the pipeline, from a clean
tree. A release's versions are made from a tag; the nightly's from any commit.

Each object carries in its metadata the pipeline's tag or commit, the DHIS2 version and the
sha256, as Sierra Leone's dumps carry who uploaded them. Writes take credentials allowed
s3:PutObject under the type's folder, from the environment, as the aws CLI takes them.
"""

import subprocess
import sys

from pipeline import manifest, provenance
from pipeline.config import BUCKET, Database, lock
from pipeline.errors import CheckFailed, UsageError


def run(database: Database, names: list[str], dry_run: bool, bucket: str = BUCKET) -> None:
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
    if not all(v.nightly for v in versions) and not state["tag"]:
        problems.append("a release publishes from a tag, and no tag points at HEAD")

    if problems:
        message = "will not publish:\n  " + "\n  ".join(problems)
        if not dry_run:
            raise UsageError(message)
        print(f"publish: dry run, would refuse: {message}", file=sys.stderr)

    label = state["tag"] or state["commit"] or "unknown"
    for name, record in records.items():
        metadata = ",".join(
            [
                f"pipeline={label}",
                f"dhis2_version={record['dhis2'].get('DHIS2_VERSION', name)}",
                f"sha256={record['dump']['sha256']}",
                f"orgunit={record['area']['orgunit']}",
            ]
        )
        uploads = [
            (database.dump(name), database.dump_name, "application/gzip"),
            (database.manifest(name), "manifest.json", "application/json"),
        ]
        for path, file, content_type in uploads:
            command = [
                "aws",
                "s3",
                "cp",
                str(path),
                f"s3://{bucket}/{database.key(name, file)}",
                "--content-type",
                content_type,
                "--metadata",
                metadata,
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
        print(f"publish: {', '.join(records)} to s3://{bucket}/{database.type}/", file=sys.stderr)
