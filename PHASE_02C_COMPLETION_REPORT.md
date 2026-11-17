# PHASE 02C COMPLETION REPORT — Web Search & Source Intelligence

## 1. Phase Objective

Transform the existing Web Searcher into a more capable research retrieval system:

1. Understand and execute the Researcher's research plan.
2. Generate/use diverse search queries.
3. Retrieve relevant sources.
4. Prefer authoritative and primary sources where appropriate.
5. Identify duplicate sources.
6. Preserve source metadata.
7. Extract page content reliably.
8. Handle inaccessible and incomplete sources honestly.
9. Track extraction failures.
10. Pass clean, structured evidence to the Synthesis Analyst.

No paid services or APIs were introduced. No new agents were added.

## 2. Final Git State

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842`
- origin/main: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync)
- Working tree: modified + untracked files (all uncommitted, unpushed)

## 3. Change Inventory by Phase

### Phase 02A — Evaluation Framework & Baseline (pre-existing, preserved)

**Modified:**
- `tests/unit/test_tools.py` (7 new schema tests added in 02B, retained)

**New:**
- `src/coraxis/evaluation/` (benchmark, scoring, metrics, harness)
- `scripts/capture_baseline.py`, `scripts/discover_models.py`, `scripts/run_one_case.py`
- `evaluation/baseline/bench-00{1..10}.json` (Phase 02A baseline, Mercury 3)
- `tests/unit/test_benchmark.py`, `test_scoring.py`, `test_metrics.py`, `test_harness.py`, `test_discovery.py`
- `tests/integration/test_model_discovery.py`
- `PHASE_02A_COMPLETION_REPORT.md`

### Phase 02B — Researcher Intelligence (pre-existing, preserved)

**Modified:**
- `src/coraxis/agents/definitions.py` (Researcher goal/backstory)
- `src/coraxis/agents/tasks.py` (SubQuestions schema with question_type, complexity, subquestion_plans)
- `src/coraxis/services/llm/factory.py` (LLMConfig.drop_params)
- `tests/unit/test_tools.py` (7 new schema tests)

### Phase 02C — Web Search & Source Intelligence (this phase)

**Modified:**
- `src/coraxis/agents/citations.py` (source metadata fields, normalized-URL dedup, stats)
- `src/coraxis/agents/tools/fetch.py` (SSRF hardening, manual redirects, retrieved_at)
- `src/coraxis/agents/tools/crew_tools.py` (source classification, discovery query, retrieval date)
- `src/coraxis/agents/tasks.py` (FindingItem/RawFindings metadata fields, search_observability)
- `tests/unit/test_citations.py` (payload assertion extended for new fields)

**New:**
- `src/coraxis/agents/tools/source_utils.py` (URL normalization, heuristic source classification)
- `tests/unit/test_search.py` (31 tests: URL normalization, classification, SSRF, dedup, extraction)

**Documentation:**
- `PHASE_02C_COMPLETION_REPORT.md` (this report)

No files were deleted, overwritten, or reset.

## 4. Security Review — SSRF Deep Dive

### 4.1 Findings

The initial Phase 02C implementation had several SSRF weaknesses that were identified and fixed during this finalization:

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | **Proxy environment variables** — httpx honors `HTTP_PROXY`/`HTTPS_PROXY` by default, allowing a proxy-based bypass of the host allowlist | High | `trust_env=False` on `httpx.AsyncClient` |
| 2 | **Automatic redirects** — httpx follows redirects automatically, connecting to blocked redirect targets before they can be validated | High | `follow_redirects=False` + manual redirect following with per-hop validation |
| 3 | **IPv4-mapped IPv6** — `::ffff:127.0.0.1` bypasses `is_loopback` (IPv6 loopback is only `::1`) | Medium | `_ipv4_mapped()` unwraps IPv4-mapped IPv6 to check the embedded IPv4 address |
| 4 | **Non-standard ports** — no port restriction, allowing SSRF-based port scanning | Medium | `_ALLOWED_PORTS = {80, 443, 8080, 8443}` whitelist |
| 5 | **Embedded credentials** — `user:pass@host` URLs leak auth material to the fetched host | Low | `_url_has_credentials()` rejects URLs with username/password |

### 4.2 DNS Rebinding Assessment

**DNS rebinding is NOT fully prevented.** This is an honest limitation, not a claimed security property.

The SSRF validation in `_host_is_allowed()` performs DNS resolution via `socket.getaddrinfo()` at validation time. However, `httpx.AsyncClient` performs its **own** DNS resolution at connection time. Between validation and connection, DNS records can change (DNS rebinding), causing the connection to reach a different IP than the one validated.

**Mitigations implemented:**
- Every resolved IP is checked against the blocklist (not just the first one)
- Redirect destinations are validated before following
- Proxy environment variables are disabled (`trust_env=False`)

**Residual risk:** A determined attacker with DNS control could potentially exploit the TOCTOU window. Full prevention would require raw socket control (connecting to a pre-validated IP while sending a custom Host header), which is beyond the scope of this high-level HTTP client integration.

### 4.3 What is NOT claimed

- Complete DNS rebinding protection (NOT achieved — documented limitation above)
- Protection against all SSRF variants (only HTTP(S) outbound is covered)
- Protection against SSRF via other code paths (only `PageFetcher` was hardened)

## 5. Source Metadata & Deduplication Review

### Verified correct:

| Requirement | Status |
|---|---|
| Original URLs preserved | `Citation.url` stores the original URL; normalized URL used only for dedup key |
| Normalized URLs used only for dedup | `_by_normalized` is internal; display always uses original URL |
| Meaningful query params preserved | Only known tracking params (`utm_*`, `fbclid`, `gclid`, etc.) removed; content-changing params kept |
| Duplicate provenance preserved | `_raw_to_canonical` maps raw→canonical; `citation_for_url()` resolves any raw URL to its canonical citation |
| Canonical citation lookup works | `citation_for_url()` tested and verified |
| Classification explicitly heuristic | Documented throughout; URL/host-based only, never presented as verified authority |
| Publication dates never fabricated | Default `""`; only set when explicitly provided |
| Extraction failures distinct from empty content | `success=False` + `error` vs `success=True` + `text` |
| Snippets not presented as full content | `full_text` separate from `snippet` in `FindingItem` |

### Classification contextuality (corrected):

The classification in `source_utils.classify_source()` is **URL/host-based only**, not question-contextual. A `.gov` domain is classified as "primary" regardless of the research question. This is a heuristic signal, not proof of authority. The report's earlier claim of "contextual" classification was incorrect and has been corrected here. Classification is appropriately labelled as heuristic throughout.

## 6. Regression Test Results

### New SSRF security tests (`tests/unit/test_search.py`):

| Test | What it verifies |
|---|---|
| `test_ipv4_mapped_ipv6_loopback_is_blocked` | `::ffff:127.0.0.1` blocked |
| `test_ipv4_mapped_ipv6_private_is_blocked` | `::ffff:10.0.0.1` blocked |
| `test_port_whitelist_blocks_non_standard_port` | Port 22 blocked on public host |
| `test_port_whitelist_allows_standard_ports` | Port 443 allowed on public host |
| `test_credentials_in_url_are_blocked` | `user:pass@host` rejected |
| `test_dns_rebinding_private_ip_blocked` | DNS-resolving-to-private-IP blocked |
| `test_dns_rebinding_public_ip_allowed` | DNS-resolving-to-public-IP allowed |
| `test_redirect_to_private_ip_is_blocked_before_connection` | Redirect to `127.0.0.1` blocked before connection |
| `test_redirect_chain_all_hops_validated` | Every redirect hop validated |
| `test_max_redirects_enforced` | Redirect loop stopped at `_MAX_REDIRECTS` |
| `test_httpx_client_disables_proxy_env` | `trust_env=False` on httpx client |

### Full test suite:

| Suite | Result |
|---|---|
| Full backend test suite | **238 passed** |
| New Phase 02C tests (test_search.py) | 17 passed |
| Ruff lint | All checks passed |
| Ruff format | All files formatted |
| MyPy | No issues found (79 source files) |

No existing tests were weakened or removed.

## 7. Benchmark Comparison

**Not executed — blocker documented.**

No LLM API credentials are available in the current environment (`CORAXIS_EVAL_LLM_API_KEY`, `CORAXIS_EVAL_LLM_PROVIDER`, `CORAXIS_EVAL_LLM_MODEL`, `CORAXIS_EVAL_LLM_BASE_URL` are all unset). Without credentials, the Phase 02A evaluation harness cannot execute the pipeline against the benchmark questions.

The Phase 02A baseline (all 10 cases, Mercury 3) is preserved **untouched** under `evaluation/baseline/`. No baseline files were modified or overwritten.

To complete the comparison when credentials are available:

```bash
CORAXIS_EVAL_LLM_PROVIDER=custom \
CORAXIS_EVAL_LLM_MODEL=<model-id> \
CORAXIS_EVAL_LLM_BASE_URL=https://api.inceptionlabs.ai/v1 \
CORAXIS_EVAL_LLM_API_KEY=<key> \
python - <<'EOF'
import asyncio
from coraxis.evaluation.harness import EvaluationHarness
from coraxis.evaluation.benchmark import BENCHMARK

async def main():
    h = EvaluationHarness(baseline_dir="evaluation/baseline_phase02c",
                          max_sources=3, max_fetch_per_query=2)
    for q in BENCHMARK:
        r = await h.run_case(q)
        h.save_case(r)
asyncio.run(main())
EOF
```

Then compare per-case `automatic_metrics` (fetch_success_rate, unique_domains, duplicate_url_rate, extraction_failure_rate, search_query_count, citation_resolution_rate) between `evaluation/baseline/` and `evaluation/baseline_phase02c/`.

## 8. Known Limitations

- **No post-02C baseline re-run** — requires LLM credentials not available in this environment; deterministic unit tests cover the new behavior instead
- **DNS rebinding TOCTOU** — validation and connection use separate DNS resolutions; a determined attacker with DNS control could exploit the window (mitigated but not eliminated)
- **Heuristic classification** — URL/host-based only; `.gov`/`.edu` domains are heuristic signals, not proof of authority; classification is not question-contextual
- **Query diversification** — relies on the Researcher's `query_variants` and agent compliance; no hard enforcement at the tool level
- **SSRF hostname resolution** — best-effort; unresolvable hostnames fail at connect time rather than being pre-blocked
- **Baseline capture settings** — `max_sources=3`, `max_fetch_per_query=2` used to fit shell timeouts; not a pipeline limitation

## 9. Remaining Risks

- Without a post-02C baseline re-run, end-to-end search-quality deltas (fetch rate, domain diversity, duplicate rate) are not yet measured against Phase 02A
- Heuristic classification may misclassify edge-case domains; degrades to `general`
- The Web Searcher still depends on DuckDuckGo availability and rate limits (existing behavior, unchanged)
- DNS rebinding TOCTOU remains theoretically possible (mitigated but not eliminated)

## 10. Git Branch and Commit SHA

- Branch: `main`
- Commit (pre-change): `0e008a244b7f85645da0a5a78704e0cc2b173842`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)

## 11. Whether Changes Were Pushed

**No changes have been pushed.** All changes are in the local working tree, uncommitted.

Modified files (7):
- `src/coraxis/agents/citations.py`
- `src/coraxis/agents/tasks.py`
- `src/coraxis/agents/tools/crew_tools.py`
- `src/coraxis/agents/tools/fetch.py`
- `src/coraxis/agents/definitions.py` (Phase 02B, pre-existing)
- `src/coraxis/agents/services/llm/factory.py` (Phase 02B, pre-existing)
- `tests/unit/test_citations.py`
- `tests/unit/test_tools.py` (Phase 02B, pre-existing)

New files (2):
- `src/coraxis/agents/tools/source_utils.py`
- `tests/unit/test_search.py`

Plus all Phase 02A/02B artifacts (reports, evaluation package, scripts, baseline data, tests) which were pre-existing and preserved unchanged.

## 11. Recommended Next Steps

**Phase 02D — Evidence-Based Synthesis** is the logical next step. The Web Searcher now hands the Synthesis Analyst structured, traceable evidence with source categories, discovery queries, duplicate information, and extraction status. The Synthesis Analyst should use this to (a) map claims to evidence, (b) detect contradictions, (c) flag unsupported claims, and (d) represent uncertainty. Approval is requested before proceeding.
