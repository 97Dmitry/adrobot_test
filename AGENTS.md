# Adrobot Keitaro wrapper

- User-facing plans, findings and documentation are in Russian.
- Follow SDD: `docs/specs/001-keitaro-wrapper/spec.md` is the requirements source.
  Read its status before implementation. Plan/tasks/verification belong beside it.
- Stack required by the assignment: FastAPI + SQLAlchemy; use Alembic migrations.
- Never put API keys in tracked files, test fixtures, frontend responses or logs.
- Campaigns created by the app and live checks must start with `test_tsybizov_`.
- The shared test account contains other people's campaigns. Live write checks
  may target only campaigns created for this project and verified by prefix/ID.
- API operations are through application/integration code; do not mutate stores
  directly. Do not automatically retry remote writes after an ambiguous failure.
- The API host requires a named User-Agent; `Adrobot-Test/1.0` was accepted.
- User explicitly authorized branches, commits, pushes, PRs and merges to main
  on 2026-11-17. Use a feature branch and reviewed PR per implementation stage.
  Stage only named relevant files; never include `.env`, local DBs or artifacts.
- Stop after opening each PR and await the user's acceptance. Merge only after
  acceptance; after creating a PR, briefly explain the decisions and verification.
- Later-stage files may be present untracked: keep them out of the current PR.
- Do not add a standalone CLI or other user entry points beyond the requested
  FastAPI API and web interface. Verify backend services with tests.
- Stream uses SQLAlchemy optimistic versioning: increment revision on every
  association/pending-state change in the same transaction; do not bypass it
  with bulk updates or rely on a Python lock for revision correctness.
- After an uncertain remote write, reading the old baseline does not prove the
  write finished. Reconciliation must not resend PUT or unlock the draft.
- Run browser checks with RUN_BROWSER=1 against FakeTracker, never the shared
  account. RUN_HTTP_LIVE=1 explicitly enables the isolated real HTTP acceptance.
- API mutations require Content-Type: application/json, including bodyless Sync.
  Default hosts are local; the app has no built-in authentication.
