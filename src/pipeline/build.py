"""`pipeline build`: the base, dbgen's build of an area at its DHIS2, 42.0.

dbgen builds into output/<build>/ (dbgen build verifies the build: schema checks, importer
validation of a sample, tracker queries) and names its dump after the build, such as
dhis2-db-mnch-QP1613.sql.gz. The pipeline takes it as the base version's dump, named after the
database's type, dhis2-db-perfland-mnch.sql.gz, beside a manifest that starts the chain.
"""

import json
import os
import shutil
import subprocess
import sys
import time

from dbgen.config import Build
from dbgen.dhis2.dump import dump_name

from pipeline import manifest, provenance
from pipeline.config import Database, dhis2_version_fits, lock
from pipeline.errors import CheckFailed, UsageError


def run(database: Database, orgunit: str) -> dict:
    base = lock().base
    build = Build(spec=database.spec, codes=(orgunit,))
    state = provenance.state()
    target = database.dump(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    database.manifest(base).unlink(missing_ok=True)
    target.unlink(missing_ok=True)

    print(f"build: dbgen build {database.spec} --orgunit {orgunit}", file=sys.stderr)
    start = time.perf_counter()
    command = [sys.executable, "-m", "dbgen.cli", "build", str(database.spec), "--orgunit", orgunit]
    if subprocess.run(command).returncode != 0:
        raise CheckFailed("dbgen build failed, its error is above")
    seconds = round(time.perf_counter() - start, 1)

    built = json.loads((build.output / "manifest.json").read_text())
    labels = built["dhis2"]
    if not dhis2_version_fits(base, labels.get("DHIS2_VERSION", "")):
        raise UsageError(
            f"lock.toml's base is {base}, but dbgen builds at DHIS2 {labels.get('DHIS2_VERSION')}"
        )
    postgres = lock().images["postgres"]
    if built["images"]["postgres"] != postgres:
        raise UsageError(
            f"dbgen builds on {built['images']['postgres']}, lock.toml's postgres is {postgres}: "
            "the chain runs on the Postgres of the build"
        )
    _link(build.output / dump_name(build), target)
    record = {
        "type": database.type,
        "version": base,
        "dump": {
            "file": target.name,
            "sha256": built["dump"]["sha256"],
            "bytes": built["dump"]["bytes"],
        },
        "dhis2": labels,
        "area": {"database": database.name, "orgunit": orgunit, "build": build.name},
        "pipeline": state,
        "dbgen": {k: built["provenance"].get(k) for k in ("version", "commit", "dirty", "clean")},
        "images": {"dhis2": built["images"]["dhis2"], "postgres": postgres},
        "chain": [
            {
                "version": base,
                "made_by": "dbgen build",
                "image": built["images"]["dhis2"],
                "dhis2": labels.get("DHIS2_VERSION"),
                "pipeline": state["commit"],
                "flyway_version": built["flyway_version"],
                "seconds": {"build": seconds},
            }
        ],
        "checks": None,
        "build": built,
    }
    path = manifest.write(database, base, record)
    print(f"build: {target} and {path.name}", file=sys.stderr)
    return record


def _link(source, target) -> None:
    """The dump under the type's name, a hard link where the file system allows."""
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)
