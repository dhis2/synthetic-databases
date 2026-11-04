class UsageError(Exception):
    """The pipeline was run wrongly, or its repository holds something it cannot take: lock.toml,
    a publish.toml, a missing fix-up. Fixed by running it differently or fixing that file."""


class CheckFailed(Exception):
    """A dump, an upgrade or a check went wrong: a migration note's query returned rows, DHIS2
    did not start or migrated where it should not, rows went missing. Fixed by a fix-up, or in
    dbgen or DHIS2."""
