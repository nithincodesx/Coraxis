# MIGRATION HARDENING COMPLETION REPORT — Phase 02D migration f531e0c07457

## 1. Problem

The Phase 02D Alembic migration
`src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_add_evidence_strength_limitations_.py`
adds three `NOT NULL` columns to `run_claims`:

- `evidence_strength` (String(20))
- `limitations` (Text)
- `contradicts` (JSON)

The original migration added these columns **without `server_default`**. On an existing database that already contains `run_claims` rows, `ALTER TABLE ... ADD COLUMN ... NOT NULL` fails because the database cannot backfill existing rows with a value. This blocks production upgrades on any non-empty database.

The SQLAlchemy model (`db/models.py:423-429`) already declares Python-side `default=` values (`"insufficient"`, `""`, `list`), and `repositories/runs.py:replace_claims` already supplies these fields on writes — but neither helps an existing table during a schema migration.

## 2. Files inspected

| File | Relevance |
|---|---|
| `src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_add_evidence_strength_limitations_.py` | The migration to harden |
| `src/coraxis/db/models.py:410-431` | `RunClaim` model — declares the new columns with `default=` and `nullable=False` |
| `src/coraxis/repositories/runs.py:292-317` | `replace_claims` — writes the new fields on every run |
| `src/coraxis/db/migrations/env.py:34-35` | Alembic uses batch mode on SQLite (table rewrite) |
| `src/coraxis/db/migrations/versions/20260916_2203_e34d49dca110_initial_schema.py:213-226` | `run_claims` table definition (id is a String UUID, not autoincrement) |

## 3. Change made

**Modified** `src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_add_evidence_strength_limitations_.py` — `upgrade()` now adds each column with a `server_default` matching the model's neutral defaults:

| Column | `server_default` | Rationale |
|---|---|---|
| `evidence_strength` | `'insufficient'` | Most conservative evidence category; never invents historical support |
| `limitations` | `''` | Empty string; no historical limitations fabricated |
| `contradicts` | `'[]'` | Empty JSON array; no historical contradictions invented |

All three remain `nullable=False`, matching the model. Existing rows are backfilled by the database during `ALTER TABLE`, so the upgrade succeeds on both empty and populated tables. Fresh database creation (`alembic upgrade head` from nothing) continues to work.

**No other files were modified.** The model, repository, and application writes were already correct and are unchanged.

The migration remains in the working tree (uncommitted), as does all Phase 02A–02F work. Nothing was committed or pushed.

## 4. Migration scenarios verified

All verified against a throwaway SQLite database using the real Alembic API (`alembic upgrade` / `downgrade`). Verification script: `/tmp/opencode/verify_migration.py` (not committed).

| # | Scenario | Result |
|---|---|---|
| 1 | Fresh DB → `alembic upgrade head` | **PASS** — `run_claims` created with all three new NOT NULL columns |
| 2 | Upgrade from parent `f7e8d9c0b1a2` with empty `run_claims` | **PASS** — columns added, zero rows |
| 3 | Upgrade from parent with **existing** `run_claims` rows | **PASS** — rows preserved, backfilled with `evidence_strength='insufficient'`, `limitations=''`, `contradicts='[]'` |
| 4 | New record insertion + retrieval via SQLAlchemy `RunClaim` model | **PASS** — evidence fields write and read correctly |
| 5 | Downgrade to parent `f7e8d9c0b1a2` | **PASS** — new columns dropped, rows preserved (2 rows survived) |

Scenario 3 is the critical production-upgrade path: it confirms a database with pre-existing `run_claims` rows can upgrade without data loss and with safe neutral defaults.

### Neutral-default principle

Per the requirements, no historical evidence strength or limitations were invented. `'insufficient'` is the deliberate conservative default (absence of evidence is not evidence of strength, consistent with Phase 02D's design), `''` and `'[]'` are empty neutral values matching the model defaults.

## 5. Regression test results

All executed and passing:

| Suite | Result |
|---|---|
| Full backend pytest (`tests/unit tests/integration`) | **All pass** — 277 collected test nodes, 0 failures |
| Ruff lint (`ruff check src tests`) | **All checks passed** |
| Ruff format check (`ruff format --check src tests`) | **103 files formatted** |
| MyPy (`mypy src/coraxis`) | **No issues found** (79 source files) |

No tests were removed, weakened, or had expectations changed to obtain a green result.

### Test-count discrepancy vs earlier Phase 02 reports

| Phase report | Cited total |
|---|---|
| Phase 02A | 187 |
| Phase 02B | 207 |
| Phase 02C | 238 |
| This run | **277** |

The count grows legitimately across phases because each phase adds new test files/cases — **no tests were removed or weakened**. Specifically:
- Phase 02C (238) → now (277): +39 nodes, consistent with Phase 02D's `test_analyst.py` (22 tests) and Phase 02E's additions to `test_report_parsing.py` (18 new tests), plus other additive coverage.
- Raw test-function definitions number 255, but pytest collects **277 nodes** because parametrized tests (`@pytest.mark.parametrize`) expand into multiple nodes per function. This is the authoritative collected count.

All 277 nodes pass in this run.

## 6. Notes on downgrade

The `downgrade()` drops the three columns. This is a destructive operation for any data written into those columns after the upgrade, which is standard Alembic behavior and acceptable for a rollback path. Row data in the pre-existing columns is preserved (verified in Scenario 5).

## 7. Final Git state

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)
- Working tree: uncommitted (Phase 02A–02F plus this migration hardening). **Nothing committed, nothing pushed.**
- Modified files (this work): `src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_add_evidence_strength_limitations_.py`
- All Phase 02A–02F changes preserved untouched.

**No commit or push was performed.** Changes remain in the local working tree awaiting explicit approval.
