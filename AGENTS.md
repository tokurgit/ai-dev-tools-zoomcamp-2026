Commands

- `uv sync` - install dependencies
- `uv run pytest` - the whole suite
- `uv run pytest auctions/tests/test_models.py` - one test file

Rules

- Dependencies are added in `pyproject.toml`. Do not add one without
  asking
- CI (`.github/workflows/ci.yml`) runs `uv run pytest` on every push and
  pull request; it fails on a failing test or a coverage drop below the
  `--cov-fail-under` floor


Documents

- `_docs/process.md` - how work is organized
<!-- - Before writing tests, read `_docs/testing-guidelines.md`
- For anything touching the UI, read `_docs/design-system.md` -->
