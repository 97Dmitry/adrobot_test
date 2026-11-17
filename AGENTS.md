# Adrobot Keitaro wrapper

- User-facing plans, findings and documentation are in Russian.
- Follow SDD: `docs/specs/001-keitaro-wrapper/spec.md` is the requirements source.
  Read its status before implementation. Plan/tasks/verification belong beside it.
- Stack required by the assignment: FastAPI + SQLAlchemy; use Alembic migrations.
- Never put API keys in tracked files, test fixtures, frontend responses or logs.
- Campaigns created by the app and live checks must start with `test_tsibizov_`.
- The shared test account contains other people's campaigns. Live write checks
  may target only campaigns created for this project and verified by prefix/ID.
- API operations are through application/integration code; do not mutate stores
  directly. Do not automatically retry remote writes after an ambiguous failure.
- The API host requires a named User-Agent; `Adrobot-Test/1.0` was accepted.
- User explicitly authorized branches, commits, pushes, PRs and merges to main
  on 2026-11-17. Use a feature branch and reviewed PR per implementation stage.
  Stage only named relevant files; never include `.env`, local DBs or artifacts.
