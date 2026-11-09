# Coraxis 2.0 — Phase 01.5 Release Verification Gate Report

**Branch:** `main`  
**HEAD:** `2eb110f` (contains Phase 01 commit `b648216`)  
**Working tree:** clean  
**Pushed to origin/main:** ✅ Yes  
**Date:** 2026-11-09  
**Phase:** 01.5 — Release Verification Gate

---

## 1. Git State Verification

| Check | Result |
|-------|--------|
| Current branch is `main` | ✅ Confirmed |
| HEAD contains Phase 01 commit `b648216` | ✅ HEAD is `2eb110f` (later than `b648216`) |
| Working tree clean | ✅ Confirmed (no uncommitted changes) |
| Commit pushed to `origin/main` | ✅ Confirmed (`2eb110f` pushed) |

---

## 2. GitHub Actions CI

**Workflow:** `.github/workflows/ci.yml`  
**Triggers:** push to `main`, pull request to `main`, `workflow_dispatch`  
**Workflow syntax:** Valid YAML, all jobs well-formed

### Jobs defined

| Job | Steps | Status |
|-----|-------|--------|
| `quality` (Lint & types) | checkout → setup Python 3.11 → install deps → ruff check → ruff format → mypy → production config smoke test | ✅ Config valid |
| `test` (Tests, SQLite, py3.11/3.12) | checkout → setup Python → install deps → pytest with coverage → upload coverage (3.11 only) | ✅ Config valid |
| `test-postgres` (Tests, Postgres) | checkout → setup Python 3.11 → install deps with postgres extra → PostgreSQL 16 service → alembic upgrade head → pytest | ✅ Config valid |
| `frontend` (Frontend, Node 20) | checkout → setup Node 20 → npm ci → tsc --noEmit → npm run build | ✅ Config valid |

### Production config smoke test

Verified locally — all 5 checks pass:
1. Valid production config boots ✅
2. Weak secret rejected in production ✅
3. Wildcard CORS rejected in production ✅
4. Open registration rejected in production ✅
5. Debug rejected in production ✅

**CI run URL:** Not available — the workflow has been pushed to `origin/main` and will trigger on the next GitHub Actions runner allocation. CI has **not yet been observed to pass** on GitHub Actions; this must be confirmed by checking the Actions tab at `https://github.com/nithincodesx/Coraxis/actions`.

---

## 3. Frontend Verification

All three commands executed locally and passed:

| Command | Result | Details |
|---------|--------|---------|
| `npm ci` | ✅ Passed | 438 packages added, 439 audited (18 pre-existing vulnerabilities, unrelated to changes) |
| `npx tsc --noEmit` | ✅ Passed | No type errors |
| `npm run build` | ✅ Passed | Next.js 16.3.1 compiled successfully, TypeScript checked, 2 static pages generated |

**Lockfile fix:** `frontend/package-lock.json` was out of sync with `package.json` (missing 43+ firebase sub-dependencies), blocking `npm ci` in CI. Synced via `npm install --no-audit --no-fund` (79 packages changed). This was a pre-existing issue, not introduced by Phase 01.

---

## 4. Security Regression Coverage

### Verified: no hardcoded fallback secret

`grep` across `src/` and `tests/` confirms **zero occurrences** of `coraxis-insecure-development-key`. All three fallback sites removed:
- `src/coraxis/core/security.py:128` — JWT encode
- `src/coraxis/core/security.py:187` — JWT decode
- `src/coraxis/core/crypto.py:65` — Fernet key derivation

### Verified: missing/empty/weak secret rejection

| Test | Result | File |
|------|--------|------|
| Empty `CORAXIS_SECRET_KEY` raises `ValueError` | ✅ Pass | `tests/unit/test_security.py` |
| Whitespace-only secret raises `ValueError` | ✅ Pass | `tests/unit/test_security.py` |
| Valid secret allows JWT round-trip | ✅ Pass | `tests/unit/test_security.py` |
| Production rejects weak/short secret | ✅ Pass | `tests/unit/test_security.py` |
| Production config smoke test (5 checks) | ✅ Pass | CI `quality` job |

### Verified: Fernet encryption/decryption

| Test | Result | File |
|------|--------|------|
| Encrypt/decrypt round-trip | ✅ Pass | `tests/unit/test_crypto.py` |
| Ciphertext differs each time (IV randomization) | ✅ Pass | `tests/unit/test_crypto.py` |
| Plaintext not in ciphertext | ✅ Pass | `tests/unit/test_crypto.py` |
| Empty values are pass-through | ✅ Pass | `tests/unit/test_crypto.py` |
| Foreign ciphertext raises actionable `ConfigurationError` | ✅ Pass | `tests/unit/test_crypto.py` |
| Missing/empty secret raises in `_fernet()` | ✅ Pass | `tests/unit/test_crypto.py` |
| Invalid `CORAXIS_ENCRYPTION_KEY` raises `ConfigurationError` | ✅ Pass | `tests/unit/test_crypto.py` |

### Verified: JWT signing and verification

| Test | Result | File |
|------|--------|------|
| Access token round-trip | ✅ Pass | `tests/unit/test_security.py` |
| Refresh token returns its jti | ✅ Pass | `tests/unit/test_security.py` |
| Token-type confusion rejected | ✅ Pass | `tests/unit/test_security.py` |
| Tampered signature rejected | ✅ Pass | `tests/unit/test_security.py` |
| Expired token rejected | ✅ Pass | `tests/unit/test_security.py` |
| Garbage token rejected | ✅ Pass | `tests/unit/test_security.py` |

### Verified: token-version invalidation (NEW TEST)

**`test_token_version_invalidation_rejects_outstanding_refresh_tokens`** (`tests/integration/test_auth_flow.py`):

This addresses the specific requirement: *"The existing test adaptation that disables the user must not replace verification of token-version invalidation."*

The test:
1. Decodes the registered Coraxis refresh JWT and confirms its `ver` claim matches `user.token_version`
2. Bumps `token_version` via `user_repo.bump_token_version()` (simulating password change / logout-all)
3. Attempts to refresh with the old token → expects 401 `unauthenticated`

**Result:** ✅ Pass — Coraxis-issued refresh tokens with stale `ver` claims are correctly rejected after `token_version` is bumped.

### Verified: account deactivation invalidation (adapted test)

**`test_changing_the_password_invalidates_outstanding_tokens`** (`tests/integration/test_auth_flow.py`):

Adapted for Firebase Auth (no Coraxis JWT `ver` on Firebase ID tokens). Disables the user account (`is_active = False`) and confirms protected routes return 401 immediately.

**Result:** ✅ Pass — deactivated users cannot access protected routes.

---

## 5. Session Identification Verification

### `GET /auth/sessions` implementation

The endpoint now extracts the `sid` claim from the bearer access token (a Coraxis JWT) and passes it to `auth_service.list_sessions()`, which flags the matching session as `is_current=true`. Firebase ID tokens (not Coraxis JWTs) result in no session being flagged current.

### Tests

| Test | Result | Details |
|------|--------|---------|
| `test_sessions_flags_only_the_active_session_as_current` | ✅ Pass | Single session flagged current; with two sessions, only the bearer token's session is current |
| `test_sessions_rejects_malformed_bearer_token` | ✅ Pass | `Bearer not-a-real-token` → 401, no crash |
| `test_sessions_rejects_expired_token` | ✅ Pass | Expired Coraxis JWT → 401 |
| `test_sessions_are_listed_and_the_current_one_is_marked` | ✅ Pass | Pre-existing test, confirms `is_current=true` |

**Result:** ✅ All session identification tests pass — only the correct active session is marked `is_current=true`.

---

## 6. Complete Test Results

| Suite | Before Phase 01.5 | After Phase 01.5 |
|-------|-------------------|------------------|
| Unit tests | 85 passed | 85 passed |
| Integration tests | 62 passed | 66 passed (+4 new) |
| **Total** | **147 passed** | **151 passed** |

### New tests added (4)

| Test | File | Purpose |
|------|------|---------|
| `test_token_version_invalidation_rejects_outstanding_refresh_tokens` | `tests/integration/test_auth_flow.py` | `token_version` bump rejects stale refresh tokens |
| `test_sessions_flags_only_the_active_session_as_current` | `tests/integration/test_auth_flow.py` | `is_current` flagged only for bearer token's session |
| `test_sessions_rejects_malformed_bearer_token` | `tests/integration/test_auth_flow.py` | Malformed tokens → 401 |
| `test_sessions_rejects_expired_token` | `tests/integration/test_auth_flow.py` | Expired tokens → 401 |

### Lint and typecheck

| Command | Result |
|---------|--------|
| `ruff check src tests` | ✅ All checks passed |
| `ruff format --check src tests` | ✅ 89 files formatted |
| `mypy src` | ✅ No issues in 73 source files |

---

## 7. Remaining Issues

| Issue | Details | Mitigation |
|-------|---------|------------|
| **CI not yet observed passing on GitHub Actions** | Workflow pushed but not yet executed by GitHub Actions runners | Check `https://github.com/nithincodesx/Coraxis/actions` to confirm all jobs pass |
| **Frontend vulnerabilities (18)** | Pre-existing `npm audit` findings (8 moderate, 9 high, 1 critical) | Not related to Phase 01 changes; address in Phase 02 if desired |
| **Firebase stub is a test double** | Integration tests stub `verify_id_token` rather than using a real Firebase emulator | Complement with end-to-end tests against Firebase emulator in Phase 02 |

---

## 8. Conclusion

All Phase 01.5 verification checks pass locally:

- ✅ Git state clean, pushed to `origin/main`
- ✅ CI workflow configured correctly (not yet observed on GitHub Actions)
- ✅ Frontend: `npm ci`, `tsc --noEmit`, `npm run build` all pass
- ✅ Security: no hardcoded fallback, missing/weak secret rejected, Fernet + JWT verified, token-version invalidation tested
- ✅ Session identification: `is_current` correctly flagged, malformed/expired tokens rejected
- ✅ **151 tests pass**, lint and typecheck clean

**Phase 01.5 is complete. Waiting for approval before Phase 02.**
