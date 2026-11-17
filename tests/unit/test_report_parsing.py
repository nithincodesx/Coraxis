"""Unit tests for result parsing and the task output schemas."""

from __future__ import annotations

import json
from functools import lru_cache

from crewai import Agent

from coraxis.agents.citations import CitationTracker
from coraxis.agents.tasks import (
    AnalyzedFindings,
    FinalReport,
    RawFindings,
    SubQuestions,
    build_pipeline_tasks,
)
from coraxis.services.research import (
    _parse_report,
    extract_citation_numbers,
    validate_report,
    validate_report_citations,
    validate_report_structure,
)


class _FakeCrewOutput:
    """Mimics the shape CrewAI hands back from ``kickoff_async``."""

    def __init__(self, *, pydantic: object | None = None, raw: str = "") -> None:
        self.pydantic = pydantic
        self.raw = raw


def test_parses_a_pydantic_result_directly() -> None:
    expected = FinalReport(markdown="# Report", executive_summary="Summary")
    result = _parse_report(_FakeCrewOutput(pydantic=expected))

    assert result.markdown == "# Report"
    assert result.executive_summary == "Summary"


def test_parses_json_in_the_raw_field() -> None:
    payload = {
        "markdown": "# From JSON",
        "executive_summary": "Parsed",
        "key_findings": ["one", "two"],
        "citations_markdown": "",
    }
    result = _parse_report(_FakeCrewOutput(raw=json.dumps(payload)))

    assert result.markdown == "# From JSON"
    assert result.key_findings == ["one", "two"]


def test_falls_back_to_markdown_when_the_model_ignores_its_schema() -> None:
    """A chatty model should still produce a usable report, not an exception."""
    prose = "# My Report\n\nI ignored the JSON schema entirely."
    result = _parse_report(_FakeCrewOutput(raw=prose))

    assert result.markdown == prose
    assert result.executive_summary == ""


def test_handles_a_plain_string_result() -> None:
    result = _parse_report("just some text")
    assert result.markdown == "just some text"


def test_handles_a_pydantic_result_from_another_model_class() -> None:
    class ForeignReport(FinalReport):
        pass

    result = _parse_report(_FakeCrewOutput(pydantic=ForeignReport(markdown="# Foreign")))
    assert result.markdown == "# Foreign"


# ─── SubQuestions normalisation ──────────────────────────────────────


def test_sub_questions_are_capped_and_deduplicated() -> None:
    model = SubQuestions(
        sub_questions=[f"Question number {index}" for index in range(12)]
        + ["Question number 0", "  ", ""]
    )
    assert len(model.sub_questions) == 7
    assert len(set(model.sub_questions)) == 7


def test_sub_questions_gain_a_question_mark() -> None:
    model = SubQuestions(sub_questions=["What is the cost", "Who owns it?"])
    assert model.sub_questions == ["What is the cost?", "Who owns it?"]


def test_sub_questions_usability_flag() -> None:
    assert not SubQuestions(sub_questions=["One?", "Two?"]).is_usable
    assert SubQuestions(sub_questions=["One?", "Two?", "Three?"]).is_usable


def test_empty_sub_questions_are_usable_false() -> None:
    assert not SubQuestions().is_usable


# ─── Task wiring ─────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _agents() -> dict[str, Agent]:
    """Build real CrewAI agents for the task-wiring tests.

    ``Task`` validates its ``agent`` field by coercing the value into an
    ``Agent``, so a duck-typed stand-in is rejected before the test can assert
    anything. These are built against a local Ollama model string, which CrewAI
    resolves lazily — constructing an ``Agent`` makes no network call.
    """
    return {
        slug: Agent(
            role=slug,
            goal=f"Act as the {slug}",
            backstory="Test fixture agent.",
            llm="ollama/llama3",
            verbose=False,
            allow_delegation=False,
        )
        for slug in ("researcher", "web_searcher", "analyst", "summarizer")
    }


def test_pipeline_builds_four_sequential_tasks() -> None:
    tasks = build_pipeline_tasks(_agents(), max_sources=6, max_fetch_per_query=4)

    assert len(tasks) == 4
    assert [task.agent.role for task in tasks] == [
        "researcher",
        "web_searcher",
        "analyst",
        "summarizer",
    ]
    # Each task declares a schema, which is what forces structured output.
    assert [task.output_json for task in tasks] == [
        SubQuestions,
        RawFindings,
        AnalyzedFindings,
        FinalReport,
    ]


def test_tasks_survive_input_interpolation() -> None:
    """Every task must be kickoff-able with ``inputs={'query': ...}``.

    CrewAI interpolates ``description`` and ``expected_output`` against the
    kickoff inputs before the model ever sees them. Any brace group that looks
    like a placeholder raises ``ValueError`` at that point, which would surface
    as a failed run rather than a failed assertion — the search task's expected
    output carries a literal ``{question, url, ...}`` field list, so this is a
    live risk rather than a hypothetical one.
    """
    tasks = build_pipeline_tasks(_agents())

    for task in tasks:
        task.interpolate_inputs_and_add_conversation_history({"query": "quantum computing"})

    # Only the first task is parameterised; the rest chain via CrewAI context.
    assert "quantum computing" in tasks[0].description
    assert "{query}" not in tasks[0].description
    # The literal field list must survive untouched.
    assert "{question, url, title, snippet, full_text, word_count, fetch_success}" in (
        tasks[1].expected_output
    )


def test_source_limits_are_reflected_in_the_search_prompt() -> None:
    tasks = build_pipeline_tasks(_agents(), max_sources=11, max_fetch_per_query=3)

    assert "up to 11 results" in tasks[1].description
    assert "best 3 results" in tasks[1].description


# ─── Report Writer task wiring ─────────────────────────────────────────


def test_report_task_carries_citation_reliability_rules() -> None:
    """The Report Writer task must instruct citation reliability, not just format."""
    tasks = build_pipeline_tasks(_agents())
    report = tasks[3]

    description = report.description
    assert report.agent.role == "summarizer"
    assert report.output_json is FinalReport
    # Citation reliability rules are present in the prompt.
    for phrase in (
        "Every factual claim requiring external support must carry an inline",
        "Citation identifiers refer only to sources actually retrieved",
        "Never invent a citation id, URL, title, author, or publication date",
        "Preserve the citation numbering",
        "If a claim has insufficient evidence, state that plainly",
        "Preserve the analyst's evidence-strength categories",
        "Directly answer the research question where evidence permits",
        "List every cited source once",
        "Do not fabricate missing metadata",
    ):
        assert phrase in description, f"missing report-prompt phrase: {phrase!r}"

    # Consistent report structure is advertised.
    for section in (
        "Executive Summary",
        "Key Findings",
        "Detailed Analysis",
        "Conflicting Findings",
        "Limitations and Uncertainties",
        "Research Gaps",
        "References",
    ):
        assert section in description


# ─── Citation extraction ───────────────────────────────────────────────


def test_extract_citation_numbers_finds_body_markers() -> None:
    assert extract_citation_numbers("See [^1] and [^2][^3] here.") == [1, 2, 3]
    assert extract_citation_numbers("No citations at all.") == []
    assert extract_citation_numbers("") == []
    assert extract_citation_numbers(None) == []  # type: ignore[arg-type]


def test_extract_citation_numbers_ignores_reference_definitions() -> None:
    """Reference definitions ([^1]: ...) are not counted as body citations."""
    markdown = "Claim.\n\n[^1]: **Title** — <https://a.example>"
    assert extract_citation_numbers(markdown) == []


# ─── Citation validation ───────────────────────────────────────────────


def _tracker_with_sources(count: int = 3) -> CitationTracker:
    tracker = CitationTracker()
    for index in range(1, count + 1):
        tracker.add_source(f"https://example.com/{index}", title=f"Source {index}")
    return tracker


def test_validate_report_citations_accepts_registered_references() -> None:
    tracker = _tracker_with_sources(3)
    assert validate_report_citations("See [^1], [^2], and [^3].", tracker) == []


def test_validate_report_citations_rejects_unregistered_references() -> None:
    tracker = _tracker_with_sources(2)
    issues = validate_report_citations("See [^1] and [^5], but [^999] is missing.", tracker)
    assert any("[^5]" in issue for issue in issues)
    assert any("[^999]" in issue for issue in issues)
    # [^1] and [^2] are registered; they should not be flagged.
    assert not any("[^1]" in issue or "[^2]" in issue for issue in issues)


def test_validate_report_citations_empty_tracker() -> None:
    tracker = CitationTracker()
    issues = validate_report_citations("See [^1].", tracker)
    assert issues == ["Report references citations that were never registered: [^1]"]


def test_validate_report_citations_no_references() -> None:
    tracker = _tracker_with_sources(2)
    assert validate_report_citations("A claim with no citations.", tracker) == []


# ─── Structural validation ─────────────────────────────────────────────


def test_validate_report_structure_passes_for_complete_report() -> None:
    report = FinalReport(
        markdown="# Report\n\n## Executive Summary\n\nSummary text.\n\n## Key Findings\n\n- One.\n",
        executive_summary="Summary text.",
        key_findings=["One."],
    )
    assert validate_report_structure(report) == []


def test_validate_report_structure_flags_empty_markdown() -> None:
    report = FinalReport(markdown="", executive_summary="S", key_findings=["K"])
    assert any("empty" in issue.lower() for issue in validate_report_structure(report))


def test_validate_report_structure_flags_missing_executive_summary() -> None:
    report = FinalReport(markdown="# Report\n\nBody.", executive_summary="", key_findings=["K"])
    assert any("executive summary" in issue.lower() for issue in validate_report_structure(report))


def test_validate_report_structure_flags_missing_key_findings() -> None:
    report = FinalReport(markdown="# Report", executive_summary="S", key_findings=[])
    assert any("key findings" in issue.lower() for issue in validate_report_structure(report))


def test_validate_report_structure_flags_duplicate_headings() -> None:
    report = FinalReport(
        markdown="## Key Findings\n\nA.\n\n## Key Findings\n\nB.",
        executive_summary="S",
        key_findings=["A", "B"],
    )
    assert any("Key Findings" in issue for issue in validate_report_structure(report))


# ─── Combined validation ───────────────────────────────────────────────


def test_validate_report_returns_empty_for_clean_report() -> None:
    tracker = _tracker_with_sources(2)
    report = FinalReport(
        markdown="Claim [^1].\n\n## Executive Summary\n\nSummary.",
        executive_summary="Summary.",
        key_findings=["Claim [^1]."],
    )
    assert validate_report(report, tracker) == []


def test_validate_report_combines_structure_and_citation_issues() -> None:
    tracker = _tracker_with_sources(1)
    report = FinalReport(
        markdown="Claim [^7].",
        executive_summary="",
        key_findings=[],
    )
    issues = validate_report(report, tracker)
    joined = " ".join(issues)
    assert "[^7]" in joined
    assert "executive summary" in joined.lower()
    assert "key findings" in joined.lower()
