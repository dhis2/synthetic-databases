"""`pipeline fetch`: a published version's dump and manifest, such as a published 43 for
`pipeline dev` to upgrade, or the published dev's manifest that `pipeline dev --if-changed`
compares. Reads are public, without credentials, from S3 itself: the bucket's website
(https://databases.dhis2.org) is CloudFront, which may serve an older object for a while after a
release overwrote it. The bucket's name has dots, so the URL is path-style: the virtual-hosted
one fails TLS."""

import json
import sys

import httpx

from pipeline import manifest
from pipeline.config import BUCKET, Database, lock
from pipeline.errors import CheckFailed

BASE_URL = f"https://s3.eu-west-1.amazonaws.com/{BUCKET}"


def run(database: Database, name: str) -> dict:
    lock().version(name)
    target = database.dir(name)
    target.mkdir(parents=True, exist_ok=True)
    with _client() as http:
        record = _manifest(http, database, name)
        if record is None:
            raise CheckFailed(f"no published {name}: {_url(database, name, 'manifest.json')}")
        dump = database.dump(name)
        partial = dump.with_name(dump.name + ".part")
        url = _url(database, name, database.dump_name)
        print(f"fetch: {url}", file=sys.stderr)
        with http.stream("GET", url) as response, partial.open("wb") as f:
            response.raise_for_status()
            for chunk in response.iter_bytes(1 << 20):
                f.write(chunk)
    partial.replace(dump)
    manifest.write(database, name, record)
    manifest.check_dump(database, name, record)
    print(
        f"fetch: {name}, DHIS2 {record['dhis2'].get('DHIS2_VERSION')}, published by pipeline "
        f"{json.dumps(record['pipeline'])}",
        file=sys.stderr,
    )
    return record


def published(database: Database, name: str) -> dict | None:
    """A published version's manifest, None if none is published."""
    with _client() as http:
        return _manifest(http, database, name)


def _manifest(http: httpx.Client, database: Database, name: str) -> dict | None:
    url = _url(database, name, "manifest.json")
    print(f"fetch: {url}", file=sys.stderr)
    response = http.get(url)
    # S3 answers 403 rather than 404 for a missing key when the reader may not list the bucket.
    if response.status_code in (403, 404):
        return None
    response.raise_for_status()
    return response.json()


def _url(database: Database, name: str, file: str) -> str:
    return f"{BASE_URL}/{database.key(name, file)}"


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60, read=600), follow_redirects=True)
