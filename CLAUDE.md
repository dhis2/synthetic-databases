# Conventions

## Dependencies

Prefer the Python standard library. Reach for a third-party dep only when stdlib genuinely
doesn't cover the need (e.g. Postgres via psycopg, DHIS2's API via httpx). When in doubt, ask
before adding to `pyproject.toml`.

dbgen (`synthetic-db-generator`) is pinned in `[tool.uv.sources]`: its release is part of what a
tag publishes, and it pins DuckDB and the DHIS2 and Postgres images of the base. Bump it
deliberately, in a pull request of its own, never as part of another change.

## Tooling

`uv` manages everything: dependencies, virtualenv, build, tests, linting. Do not suggest `pip`,
`venv`, `python -m pip`, or system-Python commands. If you need to run something, prefix with
`uv run ...` or `uv tool run ...`.

CI runs `uv run pre-commit run --all-files` (ruff, ty), `uv run pytest` and `dbgen explain`; the
tests need no Docker. To test a change end-to-end, run CI's release of the ward, which needs
Docker and takes about 10 minutes:

```sh
uv run pipeline release mnch --test
```

## Commits

Use conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`.
