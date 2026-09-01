# Draft Advisor repository

## Environment

- Run `uv sync` after checkout and whenever `pyproject.toml` or `uv.lock` changes.
- Run the CLI with `uv run draft-advisor ...`.
- Run tests with `uv run pytest`.
- Keep `uv.lock` committed with dependency changes.

## Validation

- Use recorded fixtures for deterministic tests by setting `DRAFT_ADVISOR_FIXTURES`.
- Preserve the repository's read-only Sleeper behavior; do not add pick-submission logic.
