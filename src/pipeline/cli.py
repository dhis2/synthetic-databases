"""Build a database with dbgen, upgrade it along lock.toml's versions, check every dump and publish
them. `pipeline <command> -h` tells more of a command.
"""

import argparse
import sys

from pipeline.config import Database, database, lock
from pipeline.errors import CheckFailed, UsageError

EXAMPLES = """\
examples:
  pipeline release mnch --test    the pull request job: the test area along the tree
  pipeline release mnch           build, upgrade and check every version of a release
  pipeline publish mnch --dry-run
  pipeline nightly mnch           the published 43 upgraded to dev, checked
  pipeline upgrade mnch 43.0
  pipeline check mnch 43.0
"""

# Seconds DHIS2 may take to start, with its migrations.
TIMEOUT = 7200


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(title="commands", dest="command", required=True)

    def command(name: str, help: str) -> argparse.ArgumentParser:
        p = commands.add_parser(name, help=help, description=help[0].upper() + help[1:] + ".")
        p.add_argument("database", help="a database of databases/, such as mnch")
        return p

    def area(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--test",
            action="store_true",
            help="build publish.toml's test_orgunit, the pull request job's area",
        )

    def timeout(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--timeout",
            type=int,
            default=TIMEOUT,
            metavar="SECONDS",
            help=f"how long DHIS2 may take to start and migrate (default: {TIMEOUT})",
        )

    p = command("build", "build the base version with dbgen build")
    area(p)
    p.set_defaults(func=cmd_build)

    p = command("upgrade", "upgrade a version's source dump to it")
    p.add_argument("version", help="a version of lock.toml, such as 43.0")
    timeout(p)
    p.set_defaults(func=cmd_upgrade)

    p = command("check", "check a version's dump as a consumer restores it")
    p.add_argument("version", help="a version of lock.toml, such as 43.0")
    timeout(p)
    p.set_defaults(func=cmd_check)

    p = command("release", "build, upgrade and check every version but the nightly's")
    area(p)
    timeout(p)
    p.set_defaults(func=cmd_release)

    p = command("fetch", "download a published version's dump and manifest")
    p.add_argument("version", help="a version of lock.toml, such as 43")
    p.set_defaults(func=cmd_fetch)

    p = command("nightly", "fetch the nightly's source version, upgrade it to the nightly's, check")
    p.add_argument(
        "--local",
        action="store_true",
        help="upgrade the source version in output/publish/ instead of the published one",
    )
    timeout(p)
    p.set_defaults(func=cmd_nightly)

    p = command("publish", "upload checked dumps and their manifests to the bucket")
    p.add_argument(
        "versions",
        nargs="*",
        metavar="VERSION",
        help="the versions to publish (default: a release's, every version but the nightly's)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would be uploaded and refused, upload nothing",
    )
    p.set_defaults(func=cmd_publish)

    args = parser.parse_args(argv)
    try:
        args.func(args, database(args.database))
    except UsageError as e:
        print(f"pipeline: {e}", file=sys.stderr)
        sys.exit(2)
    except CheckFailed as e:
        print(f"pipeline: {e}", file=sys.stderr)
        sys.exit(1)


def _orgunit(args: argparse.Namespace, db: Database) -> str:
    return db.test_orgunit if args.test else db.orgunit


def cmd_build(args: argparse.Namespace, db: Database) -> None:
    from pipeline import build

    build.run(db, _orgunit(args, db))


def cmd_upgrade(args: argparse.Namespace, db: Database) -> None:
    from pipeline import upgrade

    upgrade.run(db, args.version, args.timeout)


def cmd_check(args: argparse.Namespace, db: Database) -> None:
    from pipeline import check

    check.run(db, args.version, args.timeout)


def cmd_release(args: argparse.Namespace, db: Database) -> None:
    from pipeline import build, check, config, upgrade

    versions = lock().release()
    for version in versions[1:]:
        config.check_fixups(version)
    build.run(db, _orgunit(args, db))
    check.run(db, versions[0].name, args.timeout)
    for version in versions[1:]:
        upgrade.run(db, version.name, args.timeout)
        check.run(db, version.name, args.timeout)
    print(f"release: {', '.join(v.name for v in versions)} checked", file=sys.stderr)


def cmd_fetch(args: argparse.Namespace, db: Database) -> None:
    from pipeline import fetch

    fetch.run(db, args.version)


def cmd_nightly(args: argparse.Namespace, db: Database) -> None:
    from pipeline import check, fetch, upgrade

    nightly = [v for v in lock().versions.values() if v.nightly]
    if not nightly:
        raise UsageError("lock.toml has no version with nightly = true")
    for version in nightly:
        assert version.source is not None
        if not args.local:
            fetch.run(db, version.source)
        upgrade.run(db, version.name, args.timeout)
        check.run(db, version.name, args.timeout)


def cmd_publish(args: argparse.Namespace, db: Database) -> None:
    from pipeline import publish

    names = args.versions or [v.name for v in lock().release()]
    publish.run(db, names, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
