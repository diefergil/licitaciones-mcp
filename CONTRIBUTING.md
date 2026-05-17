# Contributing

Thanks for considering a contribution.

## Development Setup

```bash
uv sync --extra dev
uv run pre-commit install
uv run pytest -q
```

## Pull Requests

- Keep changes focused and explain the user-facing behavior.
- Add or update tests for parser, scoring, storage, MCP, or CLI behavior changes.
- Run `uv run pre-commit run --all-files` before opening a PR.
- Do not commit secrets, downloaded procurement datasets, database dumps, or local environment files.
- CI does not run automatically for external pull requests. Maintainers may run checks manually after reviewing the proposed changes.

## Source Data

Small anonymized or public fixtures may live under `tests/fixtures/`. Large PLACSP/TED downloads should stay outside the repository.
