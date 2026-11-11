import pytest

from pipeline import publish

POSTGRES = "ghcr.io/baosystems/postgis:16-3.5@sha256:" + "p" * 64
RUN = {
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "dhis2/synthetic-databases",
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "2",
}


def record(dhis2: dict, flyway_version: str | None) -> dict:
    return {
        "dhis2": dhis2,
        "dump": {"sha256": "s" * 64},
        "area": {"orgunit": "QP1613"},
        "images": {"postgres": POSTGRES},
        "chain": [{"flyway_version": "2.42.1"}, {"flyway_version": flyway_version}],
    }


def test_metadata_tells_the_dump_and_the_run_that_saved_it():
    dhis2 = {"DHIS2_VERSION": "2.43-SNAPSHOT", "DHIS2_BUILD_REVISION": "abc1234"}

    assert publish.metadata(record(dhis2, "2.43.22"), "v0.1.0", RUN) == {
        "saved_by": "dhis2/synthetic-databases@v0.1.0",
        "run_url": "https://github.com/dhis2/synthetic-databases/actions/runs/123/attempts/2",
        "dhis2_version": "2.43-SNAPSHOT",
        "dhis2_revision": "abc1234",
        "flyway_schema_version": "2.43.22",
        "sha256": "s" * 64,
        "orgunit_code": "QP1613",
        "postgres_image": POSTGRES,
    }


def test_metadata_leaves_out_what_is_unknown():
    fields = publish.metadata(record({}, None), "c" * 40, {})

    assert fields.keys() == {"saved_by", "sha256", "orgunit_code", "postgres_image"}


def test_a_candidate_publishes_each_version_under_rc():
    assert publish.published_name("43", candidate=True) == "rc-43"
    assert publish.published_name("43", candidate=False) == "43"


@pytest.mark.parametrize(
    ("unpinned", "tag", "candidate", "refused"),
    [
        (False, None, False, True),
        (False, "v0.1.0", False, False),
        (False, None, True, False),
        (True, None, False, False),
    ],
)
def test_only_a_release_needs_a_tag(unpinned, tag, candidate, refused):
    problem = publish.tag_problem(unpinned, tag, candidate)

    assert (problem is not None) == refused
