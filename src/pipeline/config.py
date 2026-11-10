"""What the pipeline builds, upgrades to and publishes, and where it writes.

The pipeline runs in its repository, the working directory:

lock.toml                       the base version, dbgen's build, and the DHIS2 image of each
                                version after it, with the version it upgrades from
databases/<name>/               a database: dbgen's spec and metadata, and publish.toml, its type
                                and areas
upgrades/<version>/             check.sql, pre.sql and post.sql of the upgrade to a version
output/                         what it writes (gitignored):
├── stage/, <build>/            dbgen's build (see dbgen)
├── publish/<type>/<version>/   the dump and manifest.json of a version, as uploaded to
│                               s3://databases.dhis2.org/<type>/<version>/
└── logs/<type>/<version>/      DHIS2's and Postgres's logs of its upgrade and check
"""

import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pipeline.errors import UsageError

ROOT = Path.cwd()
LOCK = ROOT / "lock.toml"
DATABASES = ROOT / "databases"
UPGRADES = ROOT / "upgrades"
OUTPUT = ROOT / "output"
PUBLISH = OUTPUT / "publish"

BUCKET = "databases.dhis2.org"
# A version as core's harness takes DB_VERSION: alphanumerics, dots, hyphens and underscores.
VERSION = re.compile(r"[A-Za-z0-9._-]+")
FIXUPS = ("check.sql", "pre.sql", "post.sql")


@dataclass(frozen=True)
class Version:
    """A version the pipeline publishes, named after its DHIS2 image's tag, such as 43.0."""

    name: str
    dhis2: str | None  # the DHIS2 image; None for the base, which dbgen's lock.toml pins
    source: str | None  # the version it is upgraded from; None for the base
    unpinned: bool = False  # follows its image's tag, published by dev.yml, not by a release

    @property
    def upgrades(self) -> Path:
        return UPGRADES / self.name


@dataclass(frozen=True)
class Lock:
    base: str
    images: dict[str, str]
    versions: dict[str, Version]  # the base and every upgrade, each after its source

    def release(self) -> list[Version]:
        """The versions a release publishes: the pinned ones, the base first."""
        return [v for v in self.versions.values() if not v.unpinned]

    def version(self, name: str) -> Version:
        if name not in self.versions:
            raise UsageError(f"no version {name!r} in lock.toml; it has {', '.join(self.versions)}")
        return self.versions[name]

    def chain(self, name: str) -> list[Version]:
        """The versions a dump of `name` goes through, from the base."""
        out = [self.version(name)]
        while out[0].source is not None:
            out.insert(0, self.versions[out[0].source])
        return out


@dataclass(frozen=True)
class Database:
    """A database of databases/<name>/ and what publish.toml says of it."""

    name: str
    type: str  # names the S3 folder and the dump, as DB_TYPE in core's harness
    orgunit: str  # the area of a release
    test_orgunit: str  # the area of the pull request job

    @property
    def spec(self) -> Path:
        return DATABASES / self.name / f"{self.name}.toml"

    def dir(self, version: str) -> Path:
        return PUBLISH / self.type / version

    def dump(self, version: str) -> Path:
        """e.g. output/publish/perfland-mnch/43/dhis2-db-perfland-mnch.sql.gz"""
        return self.dir(version) / self.dump_name

    def manifest(self, version: str) -> Path:
        return self.dir(version) / "manifest.json"

    def logs(self, version: str) -> Path:
        """DHIS2's and Postgres's logs of an upgrade or a check, which are not published."""
        return OUTPUT / "logs" / self.type / version

    @property
    def dump_name(self) -> str:
        return f"dhis2-db-{self.type}.sql.gz"

    def key(self, version: str, file: str) -> str:
        """The object key of a file of a version in the bucket."""
        return f"{self.type}/{version}/{file}"


@cache
def lock() -> Lock:
    return parse_lock(_read(LOCK))


def parse_lock(data: dict) -> Lock:
    """lock.toml's versions, checked: each upgrades from the base or a version before it, with a
    DHIS2 image pinned by digest unless unpinned, and its fix-ups in upgrades/<version>/."""
    base = data.get("base")
    if not isinstance(base, str) or not VERSION.fullmatch(base):
        raise UsageError("lock.toml: base must be the version dbgen builds, such as 42.0")
    images = data.get("images", {})
    for name in ("postgres", "curl"):
        if name not in images:
            raise UsageError(f"lock.toml: [images] needs {name}")
    versions = {base: Version(base, None, None)}
    for name, entry in data.get("versions", {}).items():
        where = f'lock.toml [versions."{name}"]'
        if not VERSION.fullmatch(name):
            raise UsageError(f"{where}: a version is letters, digits, '.', '-' and '_'")
        if name in versions:
            raise UsageError(f"{where}: {name} is the base, which dbgen builds")
        unknown = set(entry) - {"from", "dhis2", "unpinned"}
        if unknown:
            raise UsageError(f"{where}: unknown keys {', '.join(sorted(unknown))}")
        source, image = entry.get("from"), entry.get("dhis2")
        if source not in versions:
            raise UsageError(
                f"{where}: from = {source!r} must be the base or a version listed before it"
            )
        unpinned = bool(entry.get("unpinned", False))
        if not isinstance(image, str):
            raise UsageError(f"{where}: dhis2 must name the DHIS2 image")
        if not unpinned and "@sha256:" not in image:
            raise UsageError(f"{where}: pin {image} by digest, or set unpinned = true")
        if versions[source].unpinned:
            raise UsageError(f"{where}: upgrades from {source}, which is unpinned")
        versions[name] = Version(name, image, source, unpinned)
    return Lock(base, dict(images), versions)


def check_fixups(version: Version) -> None:
    missing = [f for f in FIXUPS if not (version.upgrades / f).is_file()]
    if missing:
        raise UsageError(
            f"upgrades/{version.name}/ lacks {', '.join(missing)}: every upgrade has its "
            "check.sql, pre.sql and post.sql, if only with a comment"
        )


def database(name: str) -> Database:
    path = DATABASES / name / "publish.toml"
    if not path.exists():
        names = sorted(p.parent.name for p in DATABASES.glob("*/publish.toml"))
        raise UsageError(f"no {path.relative_to(ROOT)}; the databases are {', '.join(names)}")
    data = _read(path)
    missing = [k for k in ("type", "orgunit", "test_orgunit") if not isinstance(data.get(k), str)]
    if missing:
        raise UsageError(f"{path.relative_to(ROOT)} needs {', '.join(missing)}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", data["type"]):
        raise UsageError(f"{path.relative_to(ROOT)}: type is lowercase words joined by '-'")
    return Database(name, data["type"], data["orgunit"], data["test_orgunit"])


def dhis2_version_fits(version: str, label: str) -> bool:
    """Whether an image's DHIS2_VERSION label, such as 2.43.0.1, is of the version its tag names,
    such as 43.0: 42.0 is 2.42.0, 42 any 2.42. A tag that is no number, such as dev, fits any."""
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        return True
    prefix = f"2.{version}"
    return label == prefix or label.startswith(prefix + ".")


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except FileNotFoundError as e:
        raise UsageError(
            f"no {path.name} in {path.parent}: run the pipeline in its repository"
        ) from e
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f"{path}: {e}") from e
