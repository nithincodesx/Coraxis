"""Pipeline task definitions and their output schemas.

The Pydantic models here are the contract between agents. Because each task
declares ``output_json``, CrewAI validates the model's output against the schema
and retries on mismatch — which is what stops a chatty model from handing the
next agent a prose blob instead of the structured data it needs.
"""

from __future__ import annotations

from typing import Any

from crewai import Agent, Task
from pydantic import BaseModel, Field, field_validator

MAX_SUB_QUESTIONS = 7
MIN_SUB_QUESTIONS = 3


# ─── Output schemas ──────────────────────────────────────────────────


class SubQuestions(BaseModel):
    """Researcher output: the query decomposed into answerable parts."""

    sub_questions: list[str] = Field(
        default_factory=list,
        description="Specific, searchable sub-questions covering the key angles of the topic.",
    )
    key_entities: list[str] = Field(
        default_factory=list,
        description="People, organisations, products, or concepts worth searching for by name.",
    )
    search_strategy: str = Field(
        default="", description="One or two sentences on why this decomposition was chosen."
    )

    @field_validator("sub_questions")
    @classmethod
    def _normalise(cls, value: list[str]) -> list[str]:
        """Trim, de-duplicate, and cap the list.

        Models routinely return eight or nine questions when asked for seven.
        Truncating here is cheaper than arguing with the model.
        """
        seen: set[str] = set()
        cleaned: list[str] = []
        for question in value:
            text = question.strip()
            if not text:
                continue
            if not text.endswith("?"):
                text = f"{text.rstrip('.')}?"
            if text.lower() not in seen:
                seen.add(text.lower())
                cleaned.append(text)
        return cleaned[:MAX_SUB_QUESTIONS]

    @property
    def is_usable(self) -> bool:
        return len(self.sub_questions) >= MIN_SUB_QUESTIONS


class FindingItem(BaseModel):
    """One fetched source."""

    question: str = Field(description="The sub-question this finding addresses.")
    url: str = Field(description="Source URL.")
    title: str = Field(default="", description="Page title.")
    snippet: str = Field(default="", description="Search-result snippet.")
    full_text: str = Field(default="", description="Extracted page text.")
    word_count: int = 0
    fetch_success: bool = False


class RawFindings(BaseModel):
    """Web Searcher output: what was retrieved."""

    findings: list[FindingItem] = Field(default_factory=list)
    total_sources: int = 0
    search_time_seconds: float = 0.0
    failures: list[str] = Field(
        default_factory=list, description="Queries or URLs that did not work."
    )


class SourceRef(BaseModel):
    """A source supporting a claim."""

    url: str
    title: str = ""
    relevance: float = Field(default=0.7, ge=0.0, le=1.0)
    snippet: str = ""


class Claim(BaseModel):
    """A synthesised claim."""

    claim_id: str = Field(default="", description="Identifier, if one was assigned.")
    text: str = Field(description="The claim, stated as one factual sentence.")
    supporting_sources: list[SourceRef] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    agent: str = "analyst"


class AnalyzedFindings(BaseModel):
    """Analyst output: the evaluated evidence."""

    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list, description="Where sources disagree.")
    gaps: list[str] = Field(default_factory=list, description="What could not be established.")
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ReportStats(BaseModel):
    """Numbers describing a completed run."""

    total_sources: int = 0
    total_claims: int = 0
    avg_confidence: float = 0.0
    avg_relevance: float = 0.0
    agents_used: list[str] = Field(default_factory=list)
    models_used: dict[str, str] = Field(default_factory=dict)
    runtime_seconds: float = 0.0


class FinalReport(BaseModel):
    """Report Writer output."""

    markdown: str = Field(description="The full report in markdown, with inline [^n] citations.")
    executive_summary: str = Field(default="", description="Two to three paragraphs.")
    key_findings: list[str] = Field(default_factory=list, description="Five to eight bullets.")
    citations_markdown: str = Field(default="", description="The formatted sources appendix.")
    stats: ReportStats = Field(default_factory=ReportStats)


# ─── Task construction ───────────────────────────────────────────────


def build_pipeline_tasks(
    agents: dict[str, Agent],
    *,
    max_sources: int = 8,
    max_fetch_per_query: int = 5,
) -> list[Task]:
    """Build the four sequential tasks bound to their agents."""
    decompose = Task(
        description=(
            "Analyse the research query: '{query}'.\n\n"
            "1. Break it into 4-7 specific, searchable sub-questions covering every key angle.\n"
            "2. List the key entities (people, organisations, concepts, products) to search for.\n"
            "3. Call `recall_memory` first to check for prior findings on this topic.\n\n"
            "Each sub-question must be answerable by a single web search. Be precise."
        ),
        expected_output=(
            "JSON matching the SubQuestions schema: "
            "{sub_questions: [...], key_entities: [...], search_strategy: '...'}"
        ),
        agent=agents["researcher"],
        output_json=SubQuestions,
    )

    search = Task(
        description=(
            "For EACH sub-question from the previous step:\n"
            f"1. Call `web_search` for up to {max_sources} results.\n"
            f"2. Call `fetch_page` on the best {max_fetch_per_query} results.\n"
            "3. Return structured findings for everything that fetched successfully.\n\n"
            "Prioritise authoritative sources: academic work, official documentation, "
            "reputable journalism, primary data. Skip paywalls, login walls, and "
            "low-quality aggregators. Record failures rather than inventing content."
        ),
        expected_output=(
            "JSON matching the RawFindings schema, with a findings array of "
            "{question, url, title, snippet, full_text, word_count, fetch_success}"
        ),
        agent=agents["web_searcher"],
        output_json=RawFindings,
    )

    analyse = Task(
        description=(
            "Analyse every finding from the previous step.\n\n"
            "1. Cross-reference across sub-questions. Note consensus and contradiction.\n"
            "2. Score each source's relevance to each claim from 0 to 100.\n"
            "3. Assign calibrated confidence per claim, weighing:\n"
            "   - how many independent sources support it,\n"
            "   - whether they agree,\n"
            "   - source authority and recency,\n"
            "   - how specific the evidence is.\n"
            "4. Record conflicts between sources and any gaps in the evidence.\n"
            "5. Call `register_claim` once per claim so it carries a citation in the report.\n\n"
            "Be rigorous: a claim resting on one blog post earns low confidence; a claim "
            "corroborated by three independent authoritative sources earns high confidence."
        ),
        expected_output=(
            "JSON matching the AnalyzedFindings schema: claims with supporting_sources, "
            "confidence, relevance, plus conflicts and gaps arrays"
        ),
        agent=agents["analyst"],
        output_json=AnalyzedFindings,
    )

    report = Task(
        description=(
            "Write the final markdown report from the analyst's output.\n\n"
            "Required structure:\n"
            "1. **Executive Summary** — two to three paragraphs, decision-maker ready.\n"
            "2. **Key Findings** — five to eight bullets, each with an inline citation.\n"
            "3. **Detailed Findings** — one section per major theme, evidence-backed.\n"
            "4. **Confidence Assessment** — overall, and per claim where variance is notable.\n"
            "5. **Sources Appendix** — formatted references with relevance scores.\n\n"
            "Formatting rules:\n"
            "- Inline citations as [^1], [^2], matching the Sources Appendix.\n"
            "- `###` for sections, `####` for subsections.\n"
            "- Bold key terms; blockquote direct quotations.\n"
            "- Never assert anything the evidence does not support. Where the evidence is "
            "thin, say so plainly.\n\n"
            "Write for a technical decision-maker: precise, scannable, actionable."
        ),
        expected_output=(
            "JSON matching the FinalReport schema: markdown, executive_summary, "
            "key_findings, citations_markdown, stats"
        ),
        agent=agents["summarizer"],
        output_json=FinalReport,
    )

    return [decompose, search, analyse, report]


def build_team_tasks(
    agents: list[Agent],
    *,
    query_placeholder: str,
    workflow: list[dict[str, Any]],
    coordinator_role: str | None = None,
    coordinator_instructions: str = "",
) -> list[Task]:
    """Build tasks for a user-composed team.

    When a team defines an explicit workflow, each step becomes a task. When it
    does not, every agent receives the same goal and the sequential process
    lets each build on the previous agent's output.
    """
    by_role = {agent.role: agent for agent in agents}
    tasks: list[Task] = []

    collaboration_note = (
        "Coordinate with your teammates: use `read_inbox` and `read_blackboard` to see what "
        "they have produced, and `send_message` / `blackboard_write` to share your own results."
    )

    if workflow:
        for index, step in enumerate(workflow):
            role = str(step.get("agent_name") or "")
            agent = by_role.get(role)
            if agent is None:
                agent = agents[min(index, len(agents) - 1)]
            tasks.append(
                Task(
                    description=(
                        f"{step.get('description', 'Complete your part of the workflow.')}\n\n"
                        f"Overall goal: {query_placeholder}\n"
                        f"{collaboration_note}"
                    ),
                    expected_output=str(
                        step.get("expected_output")
                        or "A complete, structured output for this step."
                    ),
                    agent=agent,
                )
            )
    else:
        for agent in agents:
            tasks.append(
                Task(
                    description=(
                        f"Handle your part of the team goal: {query_placeholder}\n\n"
                        f"{collaboration_note}"
                    ),
                    expected_output="A complete, structured output for your role.",
                    agent=agent,
                )
            )

    if coordinator_role:
        coordinator = by_role.get(coordinator_role) or agents[0]
        tasks.append(
            Task(
                description=(
                    f"You are the team coordinator. {coordinator_instructions}\n\n"
                    "Read what every teammate produced using `read_inbox` and `read_blackboard`, "
                    f"resolve any conflicts, and produce the consolidated final answer for: {query_placeholder}"
                ),
                expected_output="A single consolidated output integrating every teammate's work.",
                agent=coordinator,
            )
        )

    return tasks
