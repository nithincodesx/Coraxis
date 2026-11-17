# Coraxis Phase 02F Final Live Benchmark Report

## 1. Executive summary

The authorized ten-case Phase 02F live benchmark was executed sequentially on
2026-11-11 using real Groq requests through the Coraxis
Researcher -> Web Searcher -> Synthesis Analyst -> Report Writer pipeline.

All 10 cases reached the live CrewAI/Groq execution path, but all 10 failed
during the first research/decomposition agent execution. Groq rejected the
model's attempted tool call because the attempted `json`/`JSON` tool was not
declared in the request's tool list. No case completed the full pipeline, so
no current research-quality, evidence, citation, or final-report metrics are
available.

No mock responses, cached answers, handcrafted reports, or bypassed agents were
used.

## 2. Environment and model configuration

| Item | Value |
|---|---|
| Evaluation date | 2026-11-11 |
| Repository branch | `main` |
| Provider | Groq |
| Model | `groq/openai/gpt-oss-120b` |
| Python | 3.11.9 |
| CrewAI | 1.15.37 |
| LiteLLM | 1.105.7 |
| MCP | 1.30.0 |
| Harness limits | `max_sources=3`, `max_fetch_per_query=2` |
| Execution mode | Sequential, real live requests |
| Evaluation environment | Isolated temporary virtual environment |
| Credential handling | Loaded from configured repository settings; never printed |

The Groq compatibility adapter was present and selected for Groq. The
repository `.venv` was not used for live execution because it contained
LiteLLM 1.108.3; the exact verified dependency combination was used in the
temporary environment instead.

## 3. Ten-case execution status

| Case | Category | Status | Result |
|---|---|---|---|
| bench-001 | comparative | **Failed** | Groq rejected undeclared `JSON` tool call |
| bench-002 | technical | **Failed** | Groq rejected undeclared `json` tool call |
| bench-003 | factual | **Failed** | Groq rejected an invalid tool call |
| bench-004 | comparative | **Failed** | Groq rejected undeclared `json` tool call |
| bench-005 | time-sensitive | **Failed** | Groq rejected undeclared `json` tool call |
| bench-006 | primary-source | **Failed** | Groq rejected undeclared `json` tool call |
| bench-007 | conflicting | **Failed** | Groq rejected undeclared `JSON` tool call |
| bench-008 | multipart | **Failed** | Groq rejected undeclared `json` tool call |
| bench-009 | time-sensitive | **Failed** | Groq rejected undeclared `json` tool call |
| bench-010 | insufficient-evidence | **Failed** | Groq rejected undeclared `json` tool call |

Cases not executed: **0/10**. Every case was attempted.  
Cases completed: **0/10**.  
Cases failed: **10/10**.

The failures occurred before web search, page fetching, synthesis, report
writing, citation persistence, or final report generation. No benchmark case
was retried because the identical provider/tool-schema failure was systematic,
not transient.

## 4. Research-quality metrics

No current research-quality metrics were produced:

| Metric group | Current result |
|---|---|
| Question understanding | N/A |
| Research decomposition | N/A — decomposition call failed |
| Subquestion quality | N/A |
| Search-query diversity | N/A |
| Source discovery | N/A |
| Source relevance and quality | N/A |
| Source diversity | N/A |
| Fetch success rate | N/A |

The model generated decomposition content in failed provider responses, but it
was not accepted as a pipeline output and is not scored as a successful result.

## 5. Evidence, synthesis, and citation metrics

No case reached evidence collection or synthesis:

| Metric | Current result |
|---|---|
| Claims | N/A |
| Claims with supporting sources | N/A |
| Evidence-strength distribution | N/A |
| Citation resolution | N/A |
| Citation correctness | N/A |
| Contradictions identified | N/A |
| Limitations and knowledge gaps | N/A |
| Unsupported claims | N/A |

## 6. Final report-quality metrics

No final reports were generated:

| Metric | Current result |
|---|---|
| Executive summary quality | N/A |
| Directness | N/A |
| Completeness | N/A |
| Structure and readability | N/A |
| Evidence-to-claim traceability | N/A |
| Reference quality | N/A |
| Uncertainty handling | N/A |

## 7. Operational metrics

| Metric | Result |
|---|---|
| Completed agent executions | 0 full case pipelines |
| Failed case executions | 10 |
| Retries | 0 per case |
| API/provider errors | 10 Groq tool-validation failures |
| API cost | N/A — not reliably available |
| Token usage | N/A — not reliably available |
| Per-agent timing | N/A |
| Total successful pipeline time | N/A |

The real provider was reached and returned errors. The failure was not an
authentication failure and was not caused by the `cache_breakpoint` property;
the adapter prevented that earlier incompatibility from being the observed
failure.

## 8. Baseline comparison

The original Phase 02A baseline in `evaluation/baseline/` was not modified.
Its recorded automatic metric means are shown for reference:

| Automatic metric | Phase 02A baseline mean | Phase 02F current | Difference |
|---|---:|---:|---:|
| Total sources | 56.9 | N/A | N/A |
| Fetch success rate | 0.0416 | N/A | N/A |
| Unique domains | 33.6 | N/A | N/A |
| Citation resolution rate | 1.0 | N/A | N/A |
| Claim source coverage | 1.0 | N/A | N/A |
| Extraction failure count | 0.7 | N/A | N/A |
| Search query count | 13.8 | N/A | N/A |

The nine-dimension 0–5 rubric cannot be compared because no current case
produced a report eligible for scoring. Any numerical current score would be
fabricated. The comparison is therefore inconclusive, not a measured
regression or improvement.

## 9. Failure analysis

### Common failure

The first agent's structured decomposition request reached Groq, but the
model emitted a tool call named `json` or `JSON` that was not present in the
request's declared tools. Groq returned an `invalid_request_error` with
`tool_use_failed`. This occurred across all ten cases, with one case reporting
the equivalent “tool choice is none, but model called a tool” variant.

### Pipeline impact

- Question understanding: not completed by the pipeline.
- Decomposition: provider response was rejected.
- Search queries: not issued by the pipeline.
- Fetching: not reached.
- Evidence extraction: not reached.
- Citation tracking: not reached.
- Contradiction analysis: not reached.
- Synthesis: not reached.
- Report writing: not reached.
- Persistence: no successful case record was created.

### Root-cause classification

This is a live provider/model structured-tool compatibility failure. It is
distinct from the earlier CrewAI `cache_breakpoint` incompatibility, which was
resolved by the Groq-specific adapter and did not reappear in this run.

## 10. Output artifacts

The benchmark outputs are stored separately from the baseline:

- Run directory:
  `evaluation/phase02f_live/run_20261111T2145_utf8/`
- Environment metadata:
  `evaluation/phase02f_live/run_20261111T2145_utf8/environment.json`
- Per-case status and failure details:
  `evaluation/phase02f_live/run_20261111T2145_utf8/status.json`
- Redacted execution log:
  `evaluation/phase02f_live/run_20261111T2145_utf8/execution.log`

The output directory contains no detected API-key or authorization-header
patterns.

## 11. Limitations

1. No current quality score can be assigned because no case completed.
2. No controlled apples-to-apples quality comparison is possible.
3. Token usage and cost were not reliably available from failed requests.
4. The model's undeclared tool-call behavior prevents evaluation of downstream
   search, evidence, citation, and report-generation components.
5. The benchmark was run with the requested Groq model and exact compatibility
   versions, but no alternate model or provider was substituted.

## 12. Recommendations for a future development phase

These are recommendations only; no fixes were made during this benchmark:

1. Reproduce the first-agent request with captured non-secret tool schemas and
   inspect why the Groq model emits `json`/`JSON` instead of the declared
   CrewAI tool or structured-output path.
2. Evaluate a Groq model/configuration that reliably follows the declared
   CrewAI tool schema.
3. Add a deterministic integration test asserting that the decomposition agent
   never emits undeclared tool names.
4. After an approved fix, rerun all ten cases into a new output directory.
5. Do not alter the Phase 02A baseline or scoring rubric when rerunning.

## 13. Integrity confirmation

- Phase 02A baseline files: **unchanged**; all ten SHA-256 hashes matched the
  pre-run hashes.
- Previous evaluation records: **not overwritten**.
- New results: **stored under `evaluation/phase02f_live/`**.
- Application source and dependency manifests: **not modified during the
  benchmark**.
- API keys and authorization headers: **not printed or stored in outputs**.
- Commit: **none**.
- Push: **none**.
- Reset, stash, clean, or discard: **none**.

## Terminal summary

```text
Cases completed: 0/10
Cases failed: 10/10
Cases not executed: 0/10
Backend validation status: PASS (pytest tests/unit tests/integration)
Baseline integrity status: PASS (all 10 baseline hashes unchanged)
Report location: PHASE_02F_LIVE_BENCHMARK_FINAL_REPORT.md
Commit/push status: No commit or push
```
