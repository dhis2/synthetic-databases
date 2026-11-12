# DHIS2 Synthetic Databases

Synthetic DHIS2 tracker databases for core's [performance tests][perf-setup], one dump for each
DHIS2 version they run. The pipeline builds a database with [dbgen][dbgen] at DHIS2 42.0, upgrades
it with DHIS2's own migrations to each later version, checks every dump as a consumer restores it,
and publishes them to `s3://databases.dhis2.org`, where the perf tests' harness restores its
databases from.

[perf-setup]: https://github.com/dhis2/dhis2-core/tree/master/dhis-2/dhis-test-performance
[dbgen]: https://github.com/dhis2/synthetic-db-generator

> [!WARNING]
> Only `dev` is published yet: `42.0` to `43` come with the first release.

## Perf Land MNCH

Perf Land is a made-up country, MNCH its programs: the WHO/DHIS2 Antenatal Care (ANC) and
Electronic Immunization Registry (EIR) tracker packages. One dump per DHIS2 image tag:

| version | DHIS2 image, as `lock.toml` pins it | upgraded from | published by |
|---|---|---|---|
| `42.0` | `dhis2/core:42.0`, 2.42.0 | none, dbgen builds it | a [release](#publish) |
| `42` | `dhis2/core:42`, 2.42.7.1 | `42.0` | a release |
| `43.0` | `dhis2/core:43.0`, 2.43.0.1 | `42.0` | a release |
| `43` | `dhis2/core:43`, 2.43.2.1 | `43.0` | a release |
| `dev` | `dhis2/core-dev:latest`, unpinned | `43` | [dev](#publish), when out of date |

`s3://databases.dhis2.org/perfland-mnch/<version>/` holds the dump,
`dhis2-db-perfland-mnch.sql.gz`, and `manifest.json`, what made it. Reads are public:

```sh
aws s3 cp --no-sign-request s3://databases.dhis2.org/perfland-mnch/43/manifest.json .
```

Every dump holds the same records, with the same UIDs, names and users: a perf test's parameters
fit every version, and two versions compared measure DHIS2, not two datasets. One exception: `dev`
is built from `main`, the others from a release's tag, so while `main` changes dbgen, the spec or
the area ahead of a release, `dev` holds other records.

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

`dbgen areas databases/mnch/mnch.toml` estimates the records of every other area, and `dbgen
explain databases/mnch/mnch.toml` lists the fields each stage fills.

### Against Sierra Leone

Sierra Leone's demo database is what `TrackerTest` runs on, and its p95 thresholds come from it.
QP1613 against Sierra Leone's `dev` dump of 2026-08-12. Sierra Leone's "all" rows also count four
tracker programs too small for a row of their own, such as its malaria investigations. TEs are
tracked entities, AVs attribute values, ENs enrollments, EVs events, DVs data values and RELs
relationships. RELs are in the "all" rows only: a relationship can link tracked entities of two
programs, as a mother in ANC to her child in EIR.

| database | program | TEs | AVs | ENs | EVs | DVs | RELs |
|---|---|---|---|---|---|---|---|
| Perf Land QP1613 | ANC | 71,299 | 477,760 | 84,270 | 1,705,156 | 17,265,012 | |
| Perf Land QP1613 | EIR | 83,258 | 794,004 | 83,258 | 461,915 | 2,039,597 | |
| Perf Land QP1613 | **all** | **154,557** | **1,271,764** | **167,528** | **2,167,071** | **19,304,609** | **69,548** |
| Sierra Leone | Child Programme | 19,029 | 57,089 | 19,030 | 37,642 | 318,812 | |
| Sierra Leone | WHO RMNCH Tracker | 4,009 | 12,073 | 4,010 | 17,991 | 243,741 | |
| Sierra Leone | TB program | 50,026 | 1,000,195 | 50,028 | 49 | 104 | |
| Sierra Leone | **all** | **73,120** | **1,069,717** | **73,125** | **55,777** | **563,487** | **35** |

| database | program | TE : EN : EV : DV | AVs per TE | EVs per EN | DVs per EV |
|---|---|---|---|---|---|
| Perf Land QP1613 | ANC | 1 : 1.18 : 23.9 : 242 | 6.7 | 20.2 | 10.1 |
| Perf Land QP1613 | EIR | 1 : 1 : 5.5 : 24 | 9.5 | 5.5 | 4.4 |
| Perf Land QP1613 | **all** | **1 : 1.08 : 14.0 : 125** | **8.2** | **12.9** | **8.9** |
| Sierra Leone | Child Programme | 1 : 1 : 2.0 : 17 | 3.0 | 2.0 | 8.5 |
| Sierra Leone | WHO RMNCH Tracker | 1 : 1 : 4.5 : 61 | 3.0 | 4.5 | 13.5 |
| Sierra Leone | TB program | 1 : 1 : 0.001 : 0.002 | 20.0 | 0.001 | 2.1 |
| Sierra Leone | **all** | **1 : 1 : 0.76 : 7.7** | **14.6** | **0.76** | **10.1** |

EIR, which `PerfLandMnchTrackerTest` reads, has the shape of the Child Programme, which
`TrackerTest` reads: 4.4 times its children, each with 2.8 times its events.

Not larger: the test now runs as one clerk with the same filters every iteration, so it reads her
facility and searches her district, and a larger area adds records it never touches. On DHIS2
2.42.0, adding district QP1619, 2.56 times the records, moved the load p95 of all requests from
308-316 ms to 320-333 ms over 3 runs, while the build time and the harness's image doubled.

### Limitations

By their effect on `PerfLandMnchTrackerTest`'s queries, the largest first. The effects were
measured on the `dev` dump of 2026-11-10, by changing a copy of it.

* Every facility registers children evenly through 2020 to 2024: none starts late, closes or
  stops using DHIS2. Lists ordered by `createdAt` walk the newest tracked entities until they find
  the facility's: had the test's four facilities stopped a year before the newest record, the
  walks would take 2 to 50 times as long.
* No tracked entity has a temporary owner (break the glass) or has changed owner, and every
  enrollment and event is in its owner's org unit. With temporary owners for 1% of the children,
  the list of active enrollments takes 2 to 3 times as long, and 3 other plans change.
* ANC and EIR have the default category combo: every enrollment and event has the default
  attribute option combo. Every tracker query checks the sharing of the category options of the
  combos it reads.
* Relationships are mother and child only, between tracked entities. None links an event or an
  enrollment.
* Nothing is soft deleted.
* `created` is the clinical date: a tracked entity, its enrollment and its events are created
  the day they happen, with no back entry from paper and no sync lag of Android.
* Events are COMPLETED, SCHEDULE or SKIPPED, the last only in ANC. None is ACTIVE, OVERDUE or
  VISITED, and none is scheduled after 2024.
* A mother has one child, of her family name and facility: there are no siblings.
* Every EIR enrollment is ACTIVE, ANC's 40% ACTIVE and 60% COMPLETED (`mnch.toml`). None is
  CANCELLED.
* No tracked entity is inactive or a potential duplicate.
* No enrollment or event has notes.
* No single events, by design: MNCH's programs, the ANC and EIR packages, are tracker programs.

## Publish

Two workflows publish, from `main`:

* **A release**, `release.yml` on a tag `vX.Y.Z`: builds the district, upgrades and checks every
  version but `dev`, and uploads them all or none. Then, with the variable `CORE_PERF_TESTS`, it
  dispatches core's perf tests on them, without waiting for them: a perf test measures DHIS2.
  Dispatched from `main`, a release candidate: the same, uploaded as `<version>-rc`, such as
  `43-rc`, which core's harness runs as `DB_VERSION=43-rc`.
* **Dev**, `dev.yml` daily and by hand: builds the district, upgrades it to `43` and on to
  `dhis2/core-dev:latest`, checks it and uploads it as `dev`, only when `dev` is out of date: DHIS2
  master changed its migrations, or `main` moved. A failure of the upgrade to `dev` is a migration
  of master failing or slow on realistic data: tell core. It caches the `43` by what makes it, so
  a run for master's migrations alone skips the build: about 12 minutes instead of 40.

```sh
gh workflow run dev.yml --repo dhis2/synthetic-databases
```

Dispatched from a branch, `--ref <branch>`, dev builds, upgrades and checks, shows what it would
publish and refuse, and uploads nothing: only its publish job, run from `main`, can assume the
bucket's role.

`dev` follows master by itself, as core's nightly perf tests do. `42` and `43` move only with a
pull request and a release: a patch or major can come with migration notes that ask for checks or
fix-ups, reviewed before its dump is published.

Dispatched from another branch, either workflow builds, upgrades and checks, and uploads nothing.
`ci.yml`, on pull requests and `main`, releases the ward without upload.

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

A candidate first, which publishes every version as `<version>-rc` and leaves the release's
untouched:

```sh
gh workflow run release.yml --repo dhis2/synthetic-databases
```

Run core's perf tests on it as on a release, with `DB_VERSION=43-rc`. Then tag `main`:

```sh
git tag --sign --message v0.2.0 v0.2.0 main
git push origin v0.2.0
```

`release.yml` refuses a tag that is not on `main`, `publish` a release without a tag at HEAD and a
clean tree, and each `manifest.json` and S3 object records the tag, so a dump leads back to the
code that made it. A failure of the runner is re-run
on the same tag; a fix needs a new tag.

## How it works

```
synthetic-databases/
├── pyproject.toml, uv.lock    dbgen pinned by commit until it is tagged, and the pipeline's code
├── lock.toml                  the base, and the DHIS2 image of each version by digest
├── databases/mnch/            the spec, metadata, packages.lock.toml, and publish.toml: the areas
├── upgrades/<version>/        check.sql, pre.sql, post.sql of the upgrade to the version
├── src/pipeline/              build, upgrade, check, fetch, publish, dev
└── .github/workflows/         ci.yml, release.yml, dev.yml, each described in its header
```

A release of the area of `publish.toml`, each step described in its module of `src/pipeline/`:

1. **Build** at 42.0 with `dbgen build`, which verifies and dumps it (`build.py`).
2. **Upgrade** each version from its `from` in `lock.toml`: restore, `check.sql`, `pre.sql`,
   the version's DHIS2 migrates, `post.sql`, dump (`upgrade.py`).
3. **Check** each dump as a consumer restores it: DHIS2 starts without a migration, the records
   number as in the build, a clerk's tracker queries answer (`check.py`).
4. **Publish** every version or none, from a tag with a clean tree (`publish.py`).

`dev.yml` runs steps 1 and 2 up to `43`, or takes its `43` from its cache, then 2 to 4 for `dev`
(`dev.py`). `manifest.json` beside each dump says what made it, from dbgen's build to the last
upgrade (`manifest.py`).

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

`pipeline build`, `upgrade`, `check` and `dev` run one step, on what an earlier one left in
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
