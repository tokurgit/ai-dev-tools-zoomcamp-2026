# Latvian Real Estate Auction Alert Tool

Monitors the Latvian government e-auction site ([izsoles.ta.gov.lv](https://izsoles.ta.gov.lv/))
and emails users when new or updated real estate listings match their saved
filter criteria.

Full context: [`_docs/auction-alert-tool-scope.md`](_docs/auction-alert-tool-scope.md).

## Stack

- **Django 6.1** on **SQLite**
- **`uv`** for dependency and virtualenv management (no `pip` / `venv` directly)
- **pytest** (+ `pytest-django`) for the test suite
- Python **3.13**

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) installed
- `make` (optional, but every command below has a `make` shortcut)

## Setup

```bash
uv sync          # or: make install
```

This creates `.venv/` and installs the locked dependencies (including the dev
group). You never activate the venv manually — `uv run <cmd>` and the `make`
targets handle it.

Then set up the database:

```bash
make migrate                 # apply migrations
make load-reference-data     # load Category/Region lookups from data/*.csv
make superuser               # create an admin login (optional)
```

## Running the app

```bash
make run                     # http://127.0.0.1:8000  (admin at /admin/)
```

## Testing

```bash
make test                                        # whole suite
make test-file F=auctions/tests/test_models.py    # one file or directory
make test-k K=test_source_id_is_unique            # tests matching a name
```

Under the hood these are `uv run pytest`. Settings come from
`[tool.pytest.ini_options]` in `pyproject.toml` (`DJANGO_SETTINGS_MODULE = config.settings`),
so no extra flags are needed. You can also pass raw pytest args:

```bash
uv run pytest -x -q auctions/tests/
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: it installs
with `uv` and runs `uv run pytest`, which includes the coverage gate
(`--cov-fail-under`). The check is red if any test fails or if total coverage
drops below the committed floor.

## Common commands

| `make` target            | What it does                                             |
| ------------------------ | ------------------------------------------------------- |
| `make help`              | List all targets                                        |
| `make install` / `sync`  | Install/sync deps from the lockfile                     |
| `make test`              | Run the full test suite                                 |
| `make test-file F=...`   | Run one test file/dir                                   |
| `make test-k K=...`      | Run tests matching a `-k` name expression               |
| `make run`               | Start the dev server                                    |
| `make shell`             | Django shell                                            |
| `make migrate`           | Apply migrations                                        |
| `make migrations`        | Create migrations from model changes                    |
| `make lint-migrations`   | Fail if models have unmade migrations                   |
| `make check`             | Django system checks                                    |
| `make superuser`         | Create an admin user                                    |
| `make load-reference-data` | Load Category/Region tables from `data/*.csv`         |
| `make clean`             | Delete `db.sqlite3` and bytecode caches                 |

Without `make`, prefix any Django command with `uv run python manage.py`
(e.g. `uv run python manage.py migrate`).

## Project layout

```
config/          Django project (settings, urls, wsgi)
auctions/        Main app: models, management commands, tests
  management/commands/    load_reference_data, ...
  tests/                  pytest suite + fixtures
data/            Reference CSVs (kategorija.csv, region.csv) — see data/README.md
_docs/           Scope, process, task board, team role docs
```

## How work is organized

Tasks are GitHub issues, groomed before implementation. See
[`_docs/process.md`](_docs/process.md) and the role docs in `_docs/team/`.

## Adding dependencies

Add them to `pyproject.toml` (via `uv add` / `uv add --dev`) — **do not add one
without asking** (see [`AGENTS.md`](AGENTS.md)).
