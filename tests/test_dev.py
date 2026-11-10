import pytest

from pipeline import dev

COMMIT = "c" * 40
MIGRATED = "a" * 40
LATER = "b" * 40


def published(**step) -> dict:
    """A published dev of COMMIT, migrated by DHIS2 at MIGRATED."""
    return {
        "dhis2": {"DHIS2_BUILD_REVISION": MIGRATED},
        "chain": [
            {"version": "43"},
            {"version": "dev", "from": "43", "pipeline": COMMIT, **step},
        ],
    }


def migrations(changed: bool):
    """latest_migration_commit, where LATER has a migration commit MIGRATED has not, if changed."""
    commits = {MIGRATED: "m1", LATER: "m2" if changed else "m1"}
    return lambda revision: commits[revision]


def test_a_current_dev_needs_no_upgrade():
    assert dev.reasons(published(), COMMIT, LATER, migrations(False)) == []


def test_the_same_dhis2_revision_needs_no_lookup():
    def unreachable(revision):
        raise AssertionError("asked GitHub although the revision is the same")

    assert dev.reasons(published(), COMMIT, MIGRATED, unreachable) == []


@pytest.mark.parametrize(
    ("published_dev", "commit", "revision", "changed", "reason"),
    [
        (None, COMMIT, LATER, False, "none is published"),
        (published(), "d" * 40, LATER, False, "the pipeline is at ddddddd"),
        (published(), COMMIT, LATER, True, "changed its migrations between aaaaaaa and bbbbbbb"),
        (published(), COMMIT, None, False, "revision is unknown"),
    ],
)
def test_what_makes_dev_out_of_date(published_dev, commit, revision, changed, reason):
    found = dev.reasons(published_dev, commit, revision, migrations(changed))
    assert len(found) == 1
    assert reason in found[0]
