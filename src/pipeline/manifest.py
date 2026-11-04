"""manifest.json beside each dump: dbgen's manifest of the build, extended by the pipeline.

* type, version, the dump's file, bytes and sha256, the DHIS2 image it is for and its labels
* area: the database, the org unit, dbgen's build name
* pipeline: the commit, clean tree and tag of the pipeline that made the dump; dbgen: its version
  and commit, from the build's provenance
* images: the DHIS2 image, by digest, and the Postgres the chain ran on
* chain: each step from the build, its DHIS2, its fix-ups, the migrations Flyway ran with their
  times, and the seconds of its restore, its start and its dump
* checks: the results of `pipeline check`, null until it ran
* build: dbgen's manifest, as `dbgen build` wrote it

The bucket's object metadata repeats the tag, the DHIS2 version and the sha256 (publish.py).
"""

import json
from pathlib import Path

from pipeline.config import Database
from pipeline.errors import CheckFailed, UsageError


def read(database: Database, version: str) -> dict:
    path = database.manifest(version)
    if not path.exists():
        raise UsageError(
            f"no {path}: {version} has not been built or upgraded; run pipeline release, or "
            f"pipeline upgrade for {version}"
        )
    return json.loads(path.read_text())


def write(database: Database, version: str, manifest: dict) -> Path:
    path = database.manifest(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(manifest, indent=2) + "\n")
    partial.replace(path)
    return path


def check_dump(database: Database, version: str, manifest: dict) -> Path:
    """The dump of a version, which must be the one its manifest describes."""
    from pipeline import stack

    path = database.dump(version)
    if not path.exists():
        raise UsageError(f"no {path}, which {database.manifest(version)} describes")
    digest = stack.sha256(path)
    if digest != manifest["dump"]["sha256"]:
        raise CheckFailed(
            f"{path} has sha256 {digest}, its manifest says {manifest['dump']['sha256']}"
        )
    return path
