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

## Perf Land MNCH

Perf Land is a made-up country, MNCH its programs: the WHO/DHIS2 Antenatal Care (ANC) and
Electronic Immunization Registry (EIR) tracker packages. One dump per DHIS2 image tag:

| version | DHIS2 image, as `lock.toml` pins it | upgraded from | published by |
|---|---|---|---|
| `42.0` | `dhis2/core:42.0`, 2.42.0 | none, dbgen builds it | a [release](#publish) |
| `42` | `dhis2/core:42`, 2.42.7.1 | `42.0` | a release |
| `43.0` | `dhis2/core:43.0`, 2.43.0.1 | `42.0` | a release |
| `43` | `dhis2/core:43`, 2.43.2.1 | `43.0` | a release |
| `dev` | `dhis2/core-dev:latest`, unpinned | `43` | the [nightly](#publish), when out of date |

`s3://databases.dhis2.org/perfland-mnch/<version>/` holds the dump,
`dhis2-db-perfland-mnch.sql.gz`, and `manifest.json`, what made it. Reads are public:

```sh
aws s3 cp --no-sign-request s3://databases.dhis2.org/perfland-mnch/43/manifest.json .
```

Every dump holds the same records, with the same UIDs, names and users: a perf test's parameters
fit every version, and two versions compared measure DHIS2, not two datasets.

Run the dump of the DHIS2 you run: on any other, DHIS2 migrates it at the start of every run, and
is measured fresh out of a migration. That includes a newer patch than the pinned one: `42` and
`43` are the patches `lock.toml` pins, not what Docker Hub's tags point to today, and nothing
detects a new patch. Until a release moves the pin, the tag runs ahead of the dump, as master runs
ahead of Sierra Leone's `dev` dump.

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

Publishing overwrites a dump in place. The harness rebuilds its database image when the dump's
ETag in S3 changes, and records it in `run-simulation.env`. The bucket keeps versions, so an
overwrite that broke something can be rolled back.

### The area

`databases/mnch/publish.toml` names the area of a release, district QP1613, and CI's, ward
QP0602-02. Times are of a standard GitHub runner, 4 CPUs and 16 GB, on 2026-11-05:

| | district QP1613 | ward QP0602-02 |
|---|---|---|
| tracked entities | 154,557 | 7,043 |
| enrollments | 167,528 | 7,653 |
| events | 2.2 million | 98,243 |
| relationships | 69,548 | 3,186 |
| users | 149 | 12 |
| dump of each version | 506 to 509 MiB | 21 MiB |
| dbgen build | 13 min | 4 min |
| release: build, upgrades and checks | 47 min | 12 min |
| DHIS2's start migrating to 43.0 | 132 to 251 s | 49 s |

43.0's migrations grow with the data: on QP1613 2.43.21 takes 38 to 169 s, by runner.

The users are made for performance testing only: their password is `Perf-Test-2026!`, and the
superuser stays `admin` with `district`.

## Publish

Two workflows publish, from `main`:

* **A release**, `release.yml` on a tag `vX.Y.Z`: builds the district, upgrades and checks every
  version but `dev`, and uploads them all or none. Then, with the variable `CORE_PERF_TESTS`, it
  runs core's perf tests on them.
* **The nightly**, `nightly.yml` daily: upgrades the published `43` to `dhis2/core-dev:latest` and
  uploads it as `dev`, only when `dev` is out of date: DHIS2 master changed its migrations, `43`
  was released again, or `main` moved. A failure is a migration of master failing or slow on
  realistic data: tell core.

`dev` follows master by itself, as core's nightly perf tests do. `42` and `43` move only with a
pull request and a release: a patch or major can come with migration notes that ask for checks or
fix-ups, reviewed before its dump is published.

Until the variable `PUBLISH` is `true`, which waits for the bucket's credentials, a tag runs a
dry run and the nightly is off. `ci.yml`, on pull requests and `main`, releases the ward without
upload.

Release when what is published should change: a new DHIS2 patch or major (below), a dbgen bump,
or a change of the spec, the area or an upgrade.

### Add a DHIS2 patch or major

In a pull request, where CI tests the new image on the ward:

1. Its image by digest in `lock.toml`. A patch replaces the image of its major's latest, such as
   `43`. A major adds its first release and its latest, such as `44.0` and `44`, and `dev` then
   upgrades from `44`. A major's first release upgrades from the previous major's first, as 43.0
   from 42.0, never from a later patch, which can hold migrations it does not know; a major's
   latest upgrades from its first.
2. `upgrades/<version>/` with the queries of its [migration notes][notes] in `check.sql`, each led
   by a comment naming its note, each must return no rows.
3. The fix-ups those ask for: `pre.sql` runs before the version's DHIS2 starts, `post.sql` after
   Flyway migrated, each in one transaction. Each change says why and which note it answers. Expect
   few: the notes' fixes are mostly for data dbgen never writes. A fix-up only changes data that
   is valid in one version and must change for the next; what is wrong for every version is fixed
   in dbgen, the spec or the metadata.

Then merge, and release. `dev/check.sql` holds the 2.44 notes' queries; two read the note tables
2.43.3 removes, so drop them once 43 is 2.43.3 or later.

[notes]: https://github.com/dhis2/dhis2-releases/tree/master/releases

### Release

Optionally, a dry run first: run `release.yml` by hand on `main` (Actions, Release, Run workflow).
It builds, upgrades and checks the district, and shows what it would upload. Then tag `main`:

```sh
git tag --sign --message v0.2.0 v0.2.0 main
git push origin v0.2.0
```

`publish` refuses without a tag at HEAD and a clean tree, and each `manifest.json` and S3 object
records the tag, so a dump leads back to the code that made it. A failure of the runner is re-run
on the same tag; a fix needs a new tag.

## How it works

```
synthetic-databases/
├── pyproject.toml, uv.lock    dbgen pinned by commit until it is tagged, and the pipeline's code
├── lock.toml                  the base, and the DHIS2 image of each version by digest
├── databases/mnch/            the spec, metadata, packages.lock.toml, and publish.toml: the areas
├── upgrades/<version>/        check.sql, pre.sql, post.sql of the upgrade to the version
├── src/pipeline/              build, upgrade, check, fetch, publish, nightly
└── .github/workflows/         ci.yml, release.yml, nightly.yml, each described in its header
```

A release of the area of `publish.toml`, each step described in its module of `src/pipeline/`:

1. **Build** at 42.0 with `dbgen build`, which verifies and dumps it (`build.py`).
2. **Upgrade** each version from its `from` in `lock.toml`: restore, `check.sql`, `pre.sql`,
   the version's DHIS2 migrates, `post.sql`, dump (`upgrade.py`).
3. **Check** each dump as a consumer restores it: DHIS2 starts without a migration, the records
   number as in the build, a clerk's tracker queries answer (`check.py`).
4. **Publish** every version or none, from a tag with a clean tree (`publish.py`).

The nightly runs steps 2 to 4 for `dev` (`nightly.py`). `manifest.json` beside each dump says
what made it, from dbgen's build to the last upgrade (`manifest.py`).

## Develop

dbgen's requirements (see its README): Linux, [uv](https://docs.astral.sh/uv/) and Docker, 17 GiB
of free memory. A release of the district takes about 20 GB of disk for Docker's data and
`output/` together. The same `DBGEN_` variables cap dbgen's build stack and the pipeline's.

```sh
uv sync
uv run pre-commit install             # ruff and ty on each commit, as CI
uv run pytest                         # needs no Docker
uv run pipeline release mnch --test   # as CI: the ward, built, upgraded and checked
uv run pipeline release mnch          # as a release: the district, without the upload
uv run pipeline publish mnch --dry-run
```

`pipeline build`, `upgrade`, `check` and `nightly` run one step, on what an earlier one left in
`output/`; `pipeline <command> -h` tells more. What it writes, none of it committed:

```
output/
├── stage/, mnch-<area>/               dbgen's build
├── publish/perfland-mnch/<version>/   the dump and manifest.json, as uploaded
└── logs/perfland-mnch/<version>/      DHIS2's and Postgres's logs of the upgrade and check
```

`output` may be a link to a larger disk. Dependabot updates the actions and the uv dependencies
monthly, but not dbgen, which is bumped deliberately in a pull request of its own.

## Licence

BSD 3-Clause (`LICENSE`).
