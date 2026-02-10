# Commons-First Standard

`youtube-mcp` follows the shared baseline from `orchid_skills_commons_py`:

- Runtime config via `appsettings*.json`.
- Dependency/task management via `uv`.
- Code quality via `ruff` and `pytest`.

Reference:
- `orchid_skills_commons_py/docs/commons-first-python-quality-standard.md`

## Current repo commands

```bash
uv sync --dev
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -m "not integration and not e2e"
```

## Notes

- Runtime env selector in this repo remains `YOUTUBE_RAG__APP__ENVIRONMENT`.
- `appsettings.development.json` and `appsettings.production.json` are provided
  as compatibility aliases for cross-repo consistency.
