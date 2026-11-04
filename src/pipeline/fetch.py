"""`pipeline fetch`: a published version's dump and manifest, as the nightly upgrades the
published 43 to dev. Reads are public, over the bucket's website, without credentials."""

import json
import sys

import httpx

from pipeline import manifest
from pipeline.config import BUCKET, Database, lock

BASE_URL = f"https://{BUCKET}"


def run(database: Database, name: str) -> dict:
    lock().version(name)
    target = database.dir(name)
    target.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{database.key(name, 'manifest.json')}"
    print(f"fetch: {url}", file=sys.stderr)
    with httpx.Client(timeout=httpx.Timeout(60, read=600), follow_redirects=True) as http:
        response = http.get(url)
        response.raise_for_status()
        record = response.json()
        dump = database.dump(name)
        partial = dump.with_name(dump.name + ".part")
        url = f"{BASE_URL}/{database.key(name, database.dump_name)}"
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
