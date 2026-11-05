"""The Postgres and DHIS2 of an upgrade or a check: docker/compose.yaml, a dump restored into it,
SQL run on it, DHIS2 started on it, and a dump of it.

The database is restored as dbgen's dumps and core's harness restore them: `gunzip | psql` into
an empty database created from template0, as dhis, the role DHIS2 runs as and owns its objects
by. The stack runs capped by the same DBGEN_ variables as dbgen's (see dbgen's README).
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import psycopg
from dbgen.dhis2 import client as dbgen_client
from isal import igzip

from pipeline.config import lock
from pipeline.errors import CheckFailed, UsageError

COMPOSE_FILE = Path(__file__).parent / "docker" / "compose.yaml"
BASE_URL = "http://127.0.0.1:38080"
PG_DSN = "host=127.0.0.1 port=35432 dbname=dhis user=dhis password=dhis"
PSQL = ("psql", "--no-psqlrc", "--quiet", "--set=ON_ERROR_STOP=1", "--username=dhis")


def compose(*args: str, image: str | None = None, capture: bool = False) -> str:
    """Run docker compose on the stack, with the images of lock.toml and the given DHIS2's."""
    command, env = compose_command(*args, image=image)
    result = subprocess.run(command, env=env, capture_output=capture, text=True)
    if result.returncode != 0:
        error = result.stderr.strip() if capture else "its error is above"
        raise CheckFailed(f"docker compose {' '.join(args)} failed: {error}")
    return result.stdout if capture else ""


def compose_command(*args: str, image: str | None = None) -> tuple[list[str], dict[str, str]]:
    images = lock().images
    env = {
        **os.environ,
        **dbgen_client.caps(),
        "POSTGRES_IMAGE": images["postgres"],
        "CURL_IMAGE": images["curl"],
        # compose checks every service's image, also of those it does not start
        "DHIS2_IMAGE": image or "unset",
    }
    return ["docker", "compose", "--file", str(COMPOSE_FILE), *args], env


def reset() -> None:
    """Remove the stack and its database."""
    compose("down", "--volumes", "--remove-orphans")


@contextmanager
def database(dump: Path, log: Path) -> Generator[float]:
    """A fresh database holding the dump, for the block; removed after it, its Postgres log saved
    to `log`. Yields the seconds the restore took.

    Vacuumed and analyzed, as core's harness does before it measures: a dump has no statistics,
    so otherwise queries depend on when autovacuum runs."""
    reset()
    try:
        compose("up", "--detach", "--wait", "db")
        start = time.perf_counter()
        exec_db("createdb", "--username=dhis", "--owner=dhis", "--template=template0", "dhis")
        restore(dump)
        seconds = round(time.perf_counter() - start, 1)
        vacuum_analyze()
        yield seconds
    finally:
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(compose("logs", "--no-color", "db", capture=True))
        except CheckFailed as e:
            print(f"warning: Postgres's log not saved: {e}", file=sys.stderr)
        reset()


def exec_db(*command: str, stdin: IO[bytes] | None = None) -> None:
    args, env = compose_command("exec", "--no-TTY", "db", *command)
    result = subprocess.run(args, env=env, stdin=stdin, stdout=subprocess.DEVNULL)
    if result.returncode != 0:
        raise CheckFailed(f"{' '.join(command[:2])} in the db container failed, its error is above")


def restore(dump: Path) -> None:
    print(f"restore: {dump.name}", file=sys.stderr)
    args, env = compose_command("exec", "--no-TTY", "db", *PSQL, "--dbname=dhis")
    with subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL) as psql:
        stdin = psql.stdin
        assert stdin is not None
        try:
            with igzip.open(dump, "rb") as source:
                while chunk := source.read(1 << 20):
                    stdin.write(chunk)
        except BrokenPipeError:
            pass  # psql stopped on an error, which its exit code reports
        finally:
            stdin.close()
    if psql.returncode != 0:
        raise CheckFailed(f"psql failed to restore {dump}, its error is above")


def vacuum_analyze() -> None:
    start = time.perf_counter()
    exec_db(*PSQL, "--dbname=dhis", "--command=vacuum analyze")
    print(f"vacuum analyze: {round(time.perf_counter() - start, 1)} s", file=sys.stderr)


def connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(PG_DSN, **kwargs)


def start_dhis2(image: str, timeout: int, log: Path) -> float:
    """Start DHIS2 on the database and wait until it answers /api/ping, which it does once Flyway
    migrated and it started. Returns the seconds it took. Its log goes to `log` also when it
    fails to start."""
    print(f"dhis2: start {image}, waiting up to {timeout} s for /api/ping", file=sys.stderr)
    start = time.perf_counter()
    try:
        compose(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            str(timeout),
            "web",
            "web-healthcheck",
            image=image,
        )
    except CheckFailed as e:
        save_log(log, image)
        raise CheckFailed(f"DHIS2 {image} did not start, see {log}: {e}") from e
    seconds = round(time.perf_counter() - start, 1)
    print(f"dhis2: up in {seconds} s", file=sys.stderr)
    return seconds


def stop_dhis2(image: str, log: Path) -> None:
    compose("stop", "web-healthcheck", "web", image=image)
    save_log(log, image)


def save_log(log: Path, image: str) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(compose("logs", "--no-color", "web", image=image, capture=True))


def dump(target: Path) -> tuple[str, int, float]:
    """pg_dump the database as plain SQL, gzipped, as dbgen dumps. Returns its sha256, bytes and
    the seconds it took."""
    print(f"dump: {target}", file=sys.stderr)
    start = time.perf_counter()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    args, env = compose_command(
        "exec",
        "--no-TTY",
        "db",
        "pg_dump",
        "--no-owner",
        "--no-privileges",
        "--username=dhis",
        "dhis",
    )
    digest = hashlib.sha256()
    with subprocess.Popen(args, env=env, stdout=subprocess.PIPE) as proc:
        stdout = proc.stdout
        assert stdout is not None
        with (
            partial.open("wb") as raw,
            # As dbgen's dump: ISA-L at level 1, no name or time in the header.
            igzip.GzipFile(
                filename="", fileobj=_Hashing(raw, digest), mode="wb", compresslevel=1, mtime=0
            ) as out,
        ):
            while chunk := stdout.read(1 << 20):
                out.write(chunk)
    if proc.returncode != 0:
        partial.unlink(missing_ok=True)
        raise CheckFailed(f"pg_dump failed with exit code {proc.returncode}, its error is above")
    partial.replace(target)
    return digest.hexdigest(), target.stat().st_size, round(time.perf_counter() - start, 1)


class _Hashing:
    def __init__(self, f: IO[bytes], digest: "hashlib._Hash"):
        self._f = f
        self._digest = digest

    def write(self, b) -> int:
        self._digest.update(b)
        return self._f.write(b)

    def flush(self) -> None:
        self._f.flush()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 22):
            digest.update(chunk)
    return digest.hexdigest()


def image_ref(image: str) -> str:
    """The image by digest, pulled if missing: for the manifest, and so a tag such as
    core-dev:latest stays the same image for the rest of the run."""
    present = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
    if "@sha256:" not in image or present.returncode != 0:
        _docker("pull", "--quiet", image)
    if "@sha256:" in image:
        return image
    digests = json.loads(_docker("image", "inspect", "--format", "{{json .RepoDigests}}", image))
    repository = image.rsplit(":", 1)[0]
    pinned = [d for d in digests if d.startswith(repository + "@")]
    if not pinned:
        raise CheckFailed(f"{image} has no digest of {repository}: {digests}")
    return f"{image}@{pinned[0].split('@', 1)[1]}"


def labels(image: str) -> dict[str, str]:
    """The DHIS2_ labels of a DHIS2 image, such as DHIS2_VERSION 2.43.0.1."""
    found = json.loads(_docker("image", "inspect", "--format", "{{json .Config.Labels}}", image))
    return {k: v for k, v in sorted((found or {}).items()) if k.startswith("DHIS2_")}


def remote_labels(image: str) -> dict[str, str]:
    """The labels of an image in its registry, without pulling it: of linux/amd64, for an image
    of several platforms."""
    found = json.loads(
        _docker("buildx", "imagetools", "inspect", "--format", "{{json .Image}}", image)
    )
    config = found["config"] if "config" in found else found["linux/amd64"]["config"]
    return config.get("Labels") or {}


def _docker(*args: str) -> str:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True)
    except FileNotFoundError as e:
        raise UsageError("docker is not installed, or not on PATH") from e
    if result.returncode != 0:
        raise CheckFailed(f"docker {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout
