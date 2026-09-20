"""Unit tests for result parsing and the task output schemas."""

from __future__ import annotations

import json
from functools import lru_cache

from crewai import Agent

from coraxis.agents.tasks import (
    AnalyzedFindings,
    FinalReport,
    RawFindings,
    SubQuestions,
    build_pipeline_tasks,
)
from coraxis.services.research import _parse_report


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
