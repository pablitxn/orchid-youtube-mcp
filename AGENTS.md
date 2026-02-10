# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/` and follows a layered architecture:
- `src/domain/`: entities, value objects, and domain exceptions.
- `src/application/`: DTOs and business services (ingestion, query, chunking).
- `src/infrastructure/`: provider implementations (YouTube, LLM, embeddings, transcription, video), shared settings, runtime wiring, telemetry, and storage adapters.
- `src/adapters/`: FastAPI app, REST routes, MCP server tools, middleware.

Tests are organized in `tests/unit/`, `tests/integration/`, and `tests/e2e/`. Runtime configuration lives in `config/` (`appsettings*.json`), and maintenance utilities live in `scripts/`.

## Build, Test, and Development Commands
- `uv sync --dev`: install dependencies for local development.
- `docker-compose up -d`: start MongoDB, Qdrant, and MinIO locally.
- `uv run uvicorn src.adapters.main:app --reload --host 0.0.0.0 --port 8000`: run the API server.
- `uv run ruff check src tests`: lint and import/order checks.
- `uv run ruff format src tests`: apply formatting.
- `uv run mypy src`: strict type-checking for source code.
- `uv run pytest`: run all tests with coverage (`--cov-fail-under=80` is enforced).
- `uv run pytest -m "not integration and not e2e"`: fast local test baseline.

## Coding Style & Naming Conventions
Use Python 3.11, 4-space indentation, and a max line length of 88 (Ruff). Prefer explicit type hints and keep `src/` code mypy-clean under strict settings. Use `snake_case` for modules/functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Keep domain logic in `domain`/`application`; keep external service details in `infrastructure`.

## Testing Guidelines
Pytest is configured with:
- file pattern `test_*.py`
- function pattern `test_*`
- class pattern `Test*`

Use markers (`unit`, `integration`, `e2e`, `slow`) to scope runs. Add or update tests with any behavior change, especially for API contracts and service orchestration.

## Commit & Pull Request Guidelines
Commit messages should follow Conventional Commits (enforced in pre-commit): `feat:`, `fix:`, `docs:`, `test:`, `ci:`, etc. Example: `feat: add qdrant search fallback`.

Before opening a PR, run `uv run pre-commit run --all-files` and relevant pytest markers. PRs should include a concise description, impacted modules, linked issue(s), and evidence of testing. For API changes, include request/response examples.

## Security & Configuration Tips
Copy `.env.example` to `.env` for local secrets. Do not commit API keys or environment-specific credentials. Keep committed `config/appsettings*.json` values non-sensitive.
