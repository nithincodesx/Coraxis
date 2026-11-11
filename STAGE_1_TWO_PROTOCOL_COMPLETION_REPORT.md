# Coraxis Researcher Two-Protocol Stage 1 Completion Report

## Scope

Stage 1 added deterministic contract and regression tests only. No
two-protocol production orchestration, action ledger, or `RunCoordination`
implementation was added.

## File changed

- `tests/unit/test_two_protocol_stage1_contracts.py`

## Coverage added

- Existing Groq cache-marker adapter selection.
- Non-Groq provider behavior preservation.
- Custom-team behavior preservation.
- Existing Researcher structured-output contract.
- Built-in Groq Researcher-only provider gate.
- Protocol A native tools without structured output.
- Protocol B no tools with `output_json=SubQuestions`.
- Explicit immediate-predecessor task contexts.
- Secret-free test fixtures.

The future Stage 2 contracts are strict expected failures until the
corresponding production boundary is implemented.

## Validation

### Focused tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_two_protocol_stage1_contracts.py tests/unit/test_groq_compatibility.py -q
```

Result:

- 13 passed
- 4 strict expected failures

Expected failures:

1. Two-protocol provider selector is not implemented.
2. Protocol A task builder is not implemented.
3. Protocol B formatter builder is not implemented.
4. Explicit downstream predecessor contexts are not implemented.

### Lint

```powershell
.\.venv\Scripts\python.exe -m ruff check tests/unit/test_two_protocol_stage1_contracts.py
```

Result: passed.

## Restrictions respected

- No live API calls or benchmarks were run.
- No production source, dependency manifests, migrations, external contracts,
  `SubQuestions`, baseline data, existing reports, or evaluation outputs were
  modified.
- No commit, push, reset, clean, stash, discard, or delete operation was run.

## Limitations

Stage 2 must implement the provider gate, Protocol A/Protocol B task
boundaries, and explicit task contexts before the four expected failures can
become passing tests.

