import tomllib
from pathlib import Path

import pytest

from pipeline import config
from pipeline.errors import UsageError

ROOT = Path(__file__).parents[1]
DIGEST = "@sha256:" + "0" * 64
IMAGES = {"postgres": "postgis", "curl": "curl"}


def lock(**versions) -> dict:
    return {"base": "42.0", "images": IMAGES, "versions": versions}


def test_the_lock_lists_a_tree_from_the_base():
    parsed = config.parse_lock(tomllib.loads((ROOT / "lock.toml").read_text()))
    assert [v.name for v in parsed.release()] == ["42.0", "42", "43.0", "43"]
    assert [v.name for v in parsed.chain("dev")] == ["42.0", "43.0", "43", "dev"]
    assert [v.name for v in parsed.chain("42")] == ["42.0", "42"]
    for version in parsed.versions.values():
        if version.source is not None:
            config.check_fixups(version)


@pytest.mark.parametrize(
    ("versions", "error"),
    [
        ({"43": {"from": "43.0", "dhis2": "core:43" + DIGEST}}, "the base or a version listed"),
        ({"42": {"from": "42.0", "dhis2": "core:42"}}, "pin core:42 by digest"),
        ({"42.0": {"from": "42.0", "dhis2": "core:42" + DIGEST}}, "is the base"),
        ({"42": {"from": "42.0", "dhis2": "core:42" + DIGEST, "form": "x"}}, "unknown keys form"),
        (
            {
                "dev": {"from": "42.0", "dhis2": "core-dev:latest", "unpinned": True},
                "45": {"from": "dev", "dhis2": "core:45" + DIGEST},
            },
            "which is unpinned",
        ),
        ({"4 3": {"from": "42.0", "dhis2": "core:43" + DIGEST}}, "a version is letters"),
    ],
)
def test_the_lock_fails_on_a_version_it_cannot_upgrade_to(versions, error):
    with pytest.raises(UsageError, match=error):
        config.parse_lock(lock(**versions))


@pytest.mark.parametrize(
    ("version", "label", "fits"),
    [
        ("42.0", "2.42.0", True),
        ("42.0", "2.42.0.1", True),
        ("42", "2.42.7.1", True),
        ("43.0", "2.43.0.1", True),
        ("43", "2.43.2.1", True),
        ("43", "2.42.7.1", False),
        ("43.0", "2.43.1", False),
        ("4", "2.43.0", False),
        ("dev", "2.44-SNAPSHOT", True),
    ],
)
def test_an_image_fits_the_version_its_tag_names(version, label, fits):
    assert config.dhis2_version_fits(version, label) is fits
