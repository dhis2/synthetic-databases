"""The commit of the pipeline that runs, whether its tree is clean, and its tag."""

import subprocess
from functools import cache

from pipeline.config import ROOT


@cache
def state() -> dict:
    """Taken once, when the first command needs it, so a commit made while a release runs does
    not change what the release is recorded to run."""
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain") if commit else None
    return {
        "commit": commit,
        "dirty": None if status is None else bool(status),
        "tag": _git("describe", "--exact-match", "--tags", "HEAD") if commit else None,
    }


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
