# DHIS2 Synthetic Databases

Synthetic DHIS2 tracker databases for core's [performance tests][perf-setup], one dump for each
DHIS2 version they run. The pipeline builds a database with [dbgen][dbgen] at DHIS2 42.0, upgrades
it with DHIS2's own migrations to each later version, checks every dump as a consumer restores it,
and publishes them to `s3://databases.dhis2.org`, where the perf tests' harness restores its
databases from.

[perf-setup]: https://github.com/dhis2/dhis2-core/tree/master/dhis-2/dhis-test-performance
[dbgen]: https://github.com/dhis2/synthetic-db-generator

> [!WARNING]
> Nothing is published yet.

## What it publishes

The Perf Land MNCH database: Perf Land is a made-up country, MNCH its programs, the WHO/DHIS2
Antenatal Care (ANC) and Electronic Immunization Registry (EIR) tracker packages. Each dump is
named after the DHIS2 image tag it is for:

| S3 path | DHIS2 image | made by |
|---|---|---|
| `perfland-mnch/42.0/dhis2-db-perfland-mnch.sql.gz` | `dhis2/core:42.0`, 2.42.0 | `dbgen build` |
| `perfland-mnch/42/dhis2-db-perfland-mnch.sql.gz` | `dhis2/core:42`, 2.42.7.1 | upgrade of 42.0 |
| `perfland-mnch/43.0/dhis2-db-perfland-mnch.sql.gz` | `dhis2/core:43.0`, 2.43.0.1 | upgrade of 42.0 |
| `perfland-mnch/43/dhis2-db-perfland-mnch.sql.gz` | `dhis2/core:43`, 2.43.2.1 | upgrade of 43.0 |
| `perfland-mnch/dev/dhis2-db-perfland-mnch.sql.gz` | `dhis2/core-dev:latest` | nightly upgrade of 43 |

The upgrades only go forward, from dbgen's build at 42.0:

```
42.0 ─┬─▶ 42
      └─▶ 43.0 ─▶ 43 ─▶ dev
```

43.0 comes from 42.0, not from 42: a later 42 patch can be newer than 43.0, so it may hold
migrations 43.0 does not know. 42.0 to 43.0 is the upgrade that existed when 43.0 shipped.

Every dump holds the same records with the same UIDs, names and users, so a perf test's parameters
fit every version, and two versions compared measure DHIS2, not two datasets. Run the dump of the
version you run: the harness starts every run from the restored dump, and a dump of another
version would migrate on every run and be measured fresh out of a migration.

Beside each dump, `manifest.json` says what made it (see [Manifest](#manifest)). Reads are public:

```sh
aws s3 cp --no-sign-request s3://databases.dhis2.org/perfland-mnch/43/manifest.json .
```

### Run a perf test on it

Core's harness takes the type and version, the tag of `DHIS2_IMAGE`. Give `DHIS2_IMAGE` by
digest, the image the dump was checked with, `images.dhis2` of its manifest: a tag such as `43`
moves with each patch, and the harness does not pull it again, so a cached one may be an older
patch than the dump's.

```sh
DHIS2_IMAGE=dhis2/core:43@sha256:5a73b9de002b06ab1a4a61674325370107d79acbaec54e00594839837346fd23 \
  DB_TYPE=perfland-mnch DB_VERSION=43 \
  SIMULATION_CLASS=org.hisp.dhis.test.tracker.PerfLandMnchTrackerTest \
  MVN_ARGS=-Dprofile=smoke ./run-simulation.sh
```

`run-simulation.sh` does not take `perfland-mnch` yet: it allows `sierra-leone` and `hmis` only.

The harness caches its Postgres image by tag, and a release overwrites `42`, `43.0`, `43` and
`dev` in place, so remove the cached image to take a new dump, as with Sierra Leone. The bucket
keeps versions, so an overwrite that broke something can be rolled back.

### The area

`databases/mnch/publish.toml` names the area of a release, district QP1613, and CI's, ward
QP0602-02:

| | district QP1613 | ward QP0602-02 |
|---|---|---|
| tracked entities | 154,557 | 7,043 |
| enrollments | 167,528 | 7,653 |
| events | 2.2 million | 98,243 |
| dump | 506 MiB | 21 MiB |

The users are made for performance testing only: their password is `Perf-Test-2026!`, and the
superuser stays `admin` with `district`.

## How it works

```
synthetic-databases/
├── pyproject.toml, uv.lock    dbgen pinned by commit until it is tagged, and the pipeline's code
├── lock.toml                  the base, and the DHIS2 image of each version by digest
├── databases/mnch/            the spec, metadata, packages.lock.toml, and publish.toml: the areas
├── upgrades/<version>/        check.sql, pre.sql, post.sql of the upgrade to the version
├── src/pipeline/              build, upgrade, check, fetch, publish
└── .github/workflows/         ci.yml, release.yml, nightly.yml
```

A release of the area of `publish.toml`, each step described in its module of `src/pipeline/`:

1. **Build** at 42.0 with `dbgen build`, which verifies and dumps it (`build.py`).
2. **Upgrade** along the tree: restore, `check.sql`, `pre.sql`, the version's DHIS2 migrates,
   `post.sql`, dump (`upgrade.py`).
3. **Check** each dump as a consumer restores it: DHIS2 starts without a migration, the records
   number as in the build, a clerk's tracker queries answer (`check.py`).
4. **Publish** every version or none, from a tag with a clean tree (`publish.py`).

`dev` is the nightly's: the published 43 upgraded to `dhis2/core-dev:latest`, only when DHIS2
master changed its migrations or something here changed (`nightly.py`). A failure is a migration
of master failing or slow on realistic data: tell core.

`manifest.json` beside each dump says what made it, from dbgen's build to the last upgrade
(`manifest.py`).

## Run it

### Requirements

dbgen's (see its README): Linux, [uv](https://docs.astral.sh/uv/) and Docker, 17 GiB of free
memory, and for QP1613 about 10 GiB of disk where Docker keeps its data and 3 GiB for `output/`.
The same `DBGEN_` variables cap dbgen's build stack and the pipeline's.

### Commands

```sh
uv sync
uv run pipeline release mnch --test   # CI's: the ward along the tree
uv run pipeline release mnch          # build, upgrade and check 42.0, 42, 43.0 and 43
uv run pipeline publish mnch --dry-run
```

`pipeline build`, `upgrade`, `check` and `nightly` run one step; `pipeline <command> -h` tells
more.

What it writes, none of it committed:

```
output/
├── stage/, mnch-<area>/               dbgen's build
├── publish/perfland-mnch/<version>/   the dump and manifest.json, as uploaded
└── logs/perfland-mnch/<version>/      DHIS2's logs of the upgrade and the check
```

`output` may be a link to a larger disk.

## GitHub Actions workflows

In `.github/workflows/`, each described in its header:

* `ci.yml`, on `main` and pull requests: the checks, and a release of the ward without upload.
* `release.yml`, on a `v*` tag: the release of QP1613, its upload, then core's perf tests. Run by
  hand from a branch, a dry run.
* `nightly.yml`, daily: `dev`, when it is out of date.

## Add a DHIS2 version or a fix-up

A new DHIS2 patch or major arrives in a pull request:

1. Its image by digest in `lock.toml`, with the version it upgrades from. A major's first release
   upgrades from the previous major's first release, as 43.0 from 42.0; a major's latest from its
   first, as 43 from 43.0.
2. `upgrades/<version>/` with the queries of its [migration notes][notes] in `check.sql`, each led
   by a comment naming its note, each must return no rows.
3. The fix-ups those ask for: `pre.sql` runs before the version's DHIS2 starts, `post.sql` after
   Flyway migrated, each in one transaction. Each change says why and which note it answers. Expect
   few: the notes' fixes are mostly for data dbgen never writes. A fix-up only changes data that
   is valid in one version and must change for the next; what is wrong for every version is fixed
   in dbgen, the spec or the metadata.

Then a release, a tag. `dev/check.sql` holds the 2.44 notes' queries; two read the note tables
2.43.3 removes, so drop them once 43 is 2.43.3 or later.

[notes]: https://github.com/dhis2/dhis2-releases/tree/master/releases

## Development

```sh
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
```

The tests need no Docker. `uv run pre-commit install` runs ruff and ty on every commit, as CI
does. Dependabot updates the actions and the uv dependencies monthly, but not dbgen, which is
bumped deliberately in a pull request.

### Release

A release is a tag `vX.Y.Z` on `main`, pushed to GitHub: `release.yml` builds, upgrades, checks and
publishes every version from it.

## Licence

BSD 3-Clause (`LICENSE`).
