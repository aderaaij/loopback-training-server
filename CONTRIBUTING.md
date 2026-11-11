# Contributing to Loopback Server

Contributions are welcome — bug fixes, features, docs. This is a small project
with one maintainer, so the notes below are mostly about keeping changes easy
to review and safe for the people already running a server.

## Before you start

- **Small fixes:** open a pull request directly.
- **Features, or anything that changes a default, the API or the database
  schema:** open an issue first so we can agree on the shape before you write
  the code.

## Running the checks

CI runs three jobs on every pull request; all three must pass before a merge.
You can run the same checks locally.

**Backend** — the suite needs PostgreSQL and `pg_dump`, both of which the
compose stack provides. It creates and uses its own throwaway
`training_api_test` database.

```bash
make up
docker compose exec app python -m pytest
```

**MCP server** — no database or backend needed.

```bash
cd mcp
uv sync --locked --no-install-project --extra test --python 3.13
.venv/bin/python -m pytest -q
```

**Frontend** — `build` runs the typecheck and the production build.

```bash
cd frontend
npm ci
npm run build
npm run lint
```

CI on a first-time contributor's pull request waits for the maintainer to
approve the run, so don't worry if no checks appear straight away.

## Conventions

- **The API is metric.** Distances are meters, pace is seconds per km, weight
  is kg. Unit conversion is a display concern and stays in the client.
- **The iOS app is the other half of the API contract.** A change to a wire
  format needs a matching change in
  [loopback-training-app](https://github.com/aderaaij/loopback-training-app);
  say so in the pull request.
- **JSON casing differs per resource, on purpose.** Some resources are
  camelCase, some snake_case; `frontend/src/lib/types.ts` mirrors the API
  exactly. Follow the casing of the resource you are touching and don't
  normalize one side without the other.
- **Existing installs keep working unchanged.** A new setting needs a default
  that preserves current behaviour. Document it in the root `.env.example`,
  the README "Configuration" table, and pass it through in
  `docker-compose.yml`.
- **Schema changes go through Alembic.** Create the migration with
  `make create_migration m="..."` and commit it with the model change.
- **Dependencies are installed from the lockfiles.** If you change
  `pyproject.toml` or `package.json`, commit the updated `uv.lock` or
  `package-lock.json` too — CI fails when they drift.

## Changelog

User-visible changes get an entry in `CHANGELOG.md`. Add yours to the existing
`## [Unreleased]` section at the top, under the fitting heading (`Added`,
`Changed`, `Fixed`); create the section only if it isn't there. Don't bump the
version — that happens when a release is cut.

## Pull requests

- One change per pull request; unrelated fixes are easier to review apart.
- Say what the change does, why, and how you tested it.
- Add or update tests for backend and MCP changes.
- Keep the branch up to date with `main` if it conflicts.

`main` is what the `latest` Docker image is built from, so code only lands
there through a pull request with green CI.

## License

By contributing you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
