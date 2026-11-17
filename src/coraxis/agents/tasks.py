"""Pipeline task definitions and their output schemas.

The Pydantic models here are the contract between agents. Because each task
declares ``output_json``, CrewAI validates the model's output against the schema
and retries on mismatch — which is what stops a chatty model from handing the
next agent a prose blob instead of the structured data it needs.
"""

from __future__ import annotations

from typing import Any

from crewai import Agent, Task
from pydantic import BaseModel, Field, field_validator, model_validator

MAX_SUB_QUESTIONS = 7
MIN_SUB_QUESTIONS = 3


# ─── Output schemas ──────────────────────────────────────────────────


class PlannedSubQuestion(BaseModel):
    """One planned sub-question with execution metadata.

    The Researcher assigns a priority and an expected evidence type so the Web
    Searcher can diversify its queries and the Analyst can weigh source quality.
    """

    text: str = Field(description="The specific, searchable sub-question.")
    priority: int = Field(
        default=3,
        description="Importance rank, 1 = optional, 5 = must answer. Clamped to 1-5.",
    )
    expected_evidence_type: str = Field(
        default="",
        description="Kind of source that would best answer this (e.g. official docs, peer-reviewed, news).",
    )
    query_variants: list[str] = Field(
        default_factory=list,
        description="Alternative search phrasings to improve coverage.",
    )

    @field_validator("priority")
    @classmethod
    def _clamp_priority(cls, value: int) -> int:
        return max(1, min(5, value))


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
    question_type: str = Field(
        default="",
        description="Classification of the research need (factual, comparative, technical, multipart, conflicting, time-sensitive, primary-source, insufficient-evidence).",
    )
    complexity: str = Field(
        default="moderate",
        description="Estimated difficulty: simple, moderate, or complex. Drives how many sub-questions to plan.",
    )
    subquestion_plans: list[PlannedSubQuestion] = Field(
        default_factory=list,
        description="Rich per-sub-question plan with priority, expected evidence type, and query variants.",
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

    @field_validator("subquestion_plans")
    @classmethod
    def _normalise_plans(cls, value: list[PlannedSubQuestion]) -> list[PlannedSubQuestion]:
        """Trim and de-duplicate plans by sub-question text."""
        seen: set[str] = set()
        cleaned: list[PlannedSubQuestion] = []
        for plan in value:
            text = plan.text.strip()
            if not text:
                continue
            if not text.endswith("?"):
                text = f"{text.rstrip('.')}?"
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(PlannedSubQuestion(text=text, **plan.model_dump(exclude={"text"})))
        return cleaned[:MAX_SUB_QUESTIONS]

    @field_validator("complexity")
    @classmethod
    def _normalise_complexity(cls, value: str) -> str:
        value = (value or "moderate").strip().lower()
        return value if value in ("simple", "moderate", "complex") else "moderate"

    @model_validator(mode="after")
    def _sync_sub_questions_from_plans(self) -> SubQuestions:
        """Populate sub_questions from subquestion_plans when sub_questions is empty.

        Keeps the legacy flat list in sync with the rich plans so downstream
        agents (Web Searcher) that consume sub_questions continue to work.
        """
        if not self.sub_questions and self.subquestion_plans:
            self.sub_questions = [plan.text for plan in self.subquestion_plans]
        return self

    @property
    def is_usable(self) -> bool:
        return len(self.sub_questions) >= MIN_SUB_QUESTIONS

    @property
    def planned_questions(self) -> list[str]:
        """Sub-question texts, preferring plans when available."""
        if self.subquestion_plans:
            return [plan.text for plan in self.subquestion_plans]
        return list(self.sub_questions)


class FindingItem(BaseModel):
    """One fetched source."""

    question: str = Field(description="The sub-question this finding addresses.")
    url: str = Field(description="Source URL.")
    title: str = Field(default="", description="Page title.")
    snippet: str = Field(default="", description="Search-result snippet.")
    full_text: str = Field(default="", description="Extracted page text.")
    word_count: int = 0
    fetch_success: bool = False
    #: Heuristic source category (primary / academic / news / official_documentation / general).
    source_category: str = Field(default="general", description="Heuristic source category.")
    #: Publication date if discoverable, ISO-8601 where possible.
    publication_date: str = Field(default="", description="Source publication date.")
    #: Retrieval timestamp, ISO-8601.
    retrieval_date: str = Field(default="", description="When the source was retrieved.")
    #: Search query that discovered this source.
    discovery_query: str = Field(default="", description="Query that surfaced this source.")
    #: Citation id of the canonical source when this URL is a duplicate.
    duplicate_of: str = Field(default="", description="Canonical source id if duplicated.")
    #: Extraction status: success / failed / blocked / empty.
    extraction_status: str = Field(default="", description="Content extraction outcome.")


class RawFindings(BaseModel):
    """Web Searcher output: what was retrieved."""

    findings: list[FindingItem] = Field(default_factory=list)
    total_sources: int = 0
    search_time_seconds: float = 0.0
    failures: list[str] = Field(
        default_factory=list, description="Queries or URLs that did not work."
    )
    #: Per-query observability: query, category, result count, accepted count, errors.
    search_observability: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Observability record for each search query executed.",
    )


class SourceRef(BaseModel):
    """A source supporting a claim."""

    url: str
    title: str = ""
    relevance: float = Field(default=0.7, ge=0.0, le=1.0)
    snippet: str = ""
    #: Stable citation identifier (``cite_N``) assigned by the citation tracker.
    #: Empty when the source was not registered in the tracker.
    citation_id: str = Field(
        default="", description="Stable citation identifier (cite_N) for this source."
    )


class Claim(BaseModel):
    """A synthesised claim with evidence traceability."""

    claim_id: str = Field(default="", description="Identifier, if one was assigned.")
    text: str = Field(description="The claim, stated as one factual sentence.")
    supporting_sources: list[SourceRef] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    agent: str = "analyst"
    #: Evidence strength category: high / moderate / low / insufficient / conflicted.
    evidence_strength: str = Field(
        default="insufficient",
        description="Evidence strength category: high / moderate / low / insufficient / conflicted.",
    )
    #: Limitations or caveats about the evidence supporting this claim.
    limitations: str = Field(
        default="", description="Limitations or caveats about the supporting evidence."
    )
    #: Claim identifiers this claim contradicts.
    contradicts: list[str] = Field(
        default_factory=list,
        description="Identifiers of claims this claim materially disagrees with.",
    )

    @field_validator("evidence_strength")
    @classmethod
    def _normalise_evidence_strength(cls, value: str) -> str:
        value = (value or "insufficient").strip().lower()
        allowed = {"high", "moderate", "low", "insufficient", "conflicted"}
        return value if value in allowed else "insufficient"

    @model_validator(mode="after")
    def _enforce_evidence_strength_from_sources(self: Claim) -> Claim:
        """A claim with no supporting sources cannot claim high/moderate/conflicted strength.

        If no sources are registered, downgrade to 'insufficient'. This is a
        conservative default: absence of evidence is not evidence of strength.
        """
        if not self.supporting_sources and self.evidence_strength not in {
            "insufficient",
        }:
            self.evidence_strength = "insufficient"
        return self


class ConflictPair(BaseModel):
    """A pair of claims that materially disagree."""

    claim_a: str = Field(description="Identifier of the first conflicting claim.")
    claim_b: str = Field(description="Identifier of the second conflicting claim.")
    description: str = Field(
        default="", description="Description of the nature of the disagreement."
    )


class AnalyzedFindings(BaseModel):
    """Analyst output: the evaluated evidence."""

    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list, description="Where sources disagree.")
    gaps: list[str] = Field(default_factory=list, description="What could not be established.")
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Structured claim pairs that materially disagree, with descriptions.
    conflict_pairs: list[ConflictPair] = Field(
        default_factory=list,
        description="Structured pairs of claims that materially disagree.",
    )


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
            "1. Classify the question type: factual, comparative, technical, multipart, "
            "conflicting, time-sensitive, primary-source, or insufficient-evidence.\n"
            "2. Estimate complexity: simple (one direct answer), moderate (several angles), "
            "or complex (many interdependent parts).\n"
            "3. Break it into searchable sub-questions covering every key angle. Use "
            "3-4 sub-questions for simple questions, 4-7 for complex ones.\n"
            "4. For each sub-question, assign a priority (1-5, 5 = must answer), an "
            "expected evidence type (official docs, peer-reviewed, news, etc.), and "
            "1-2 alternative search phrasings (query variants) to improve coverage.\n"
            "5. List the key entities (people, organisations, concepts, products) to search for.\n"
            "6. Call `recall_memory` first to check for prior findings on this topic.\n\n"
            "Each sub-question must be answerable by a single web search. Be precise. "
            "Avoid redundant sub-questions that ask the same thing differently."
        ),
        expected_output=(
            "JSON matching the SubQuestions schema: "
            "{question_type: '...', complexity: '...', sub_questions: [...], "
            "subquestion_plans: [{text: '...', priority: 1-5, expected_evidence_type: '...', "
            "query_variants: [...]}], key_entities: [...], search_strategy: '...'}"
        ),
        agent=agents["researcher"],
        output_json=SubQuestions,
    )

    search = Task(
        description=(
            "For EACH sub-question from the previous step:\n"
            f"1. Call `web_search` for up to {max_sources} results, trying the planned "
            "query variants first when provided.\n"
            f"2. Call `fetch_page` on the best {max_fetch_per_query} results.\n"
            "3. Prioritise higher-priority sub-questions (priority 4-5) first.\n"
            "4. Return structured findings for everything that fetched successfully.\n\n"
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
            "1. Cross-reference findings across sub-questions. Note consensus and contradiction.\n"
            "2. For each claim, assign evidence strength: high / moderate / low / insufficient / conflicted.\n"
            "   - high: multiple independent, authoritative sources agree\n"
            "   - moderate: relevant evidence exists, but corroboration is limited\n"
            "   - low: weak, indirect, or incomplete evidence\n"
            "   - insufficient: evidence does not support a reliable conclusion\n"
            "   - conflicted: credible sources materially disagree\n"
            "3. Score each source's relevance to each claim from 0 to 100.\n"
            "4. Assign calibrated confidence per claim, weighing:\n"
            "   - how many independent sources support it,\n"
            "   - whether they agree,\n"
            "   - source authority and recency,\n"
            "   - how specific the evidence is.\n"
            "5. Record conflicts between sources as conflict pairs (claim_a, claim_b, description).\n"
            "6. Record any gaps in the evidence (what could not be established).\n"
            "7. Call `register_claim` once per claim so it carries a citation in the report.\n"
            "   - Every factual claim must cite at least one retrieved source via citation id.\n"
            "   - Never invent citation identifiers or cite sources that were not retrieved.\n"
            "   - If evidence is insufficient, mark evidence_strength as 'insufficient' and say so plainly.\n"
            "   - Do not treat duplicate URLs or copied content as independent corroboration.\n\n"
            "Be rigorous: a claim resting on one blog post earns low confidence; a claim "
            "corroborated by three independent authoritative sources earns high confidence."
        ),
        expected_output=(
            "JSON matching the AnalyzedFindings schema: claims with supporting_sources "
            "(each including citation_id), confidence, relevance, evidence_strength, "
            "limitations, contradicts, plus conflicts, conflict_pairs, and gaps arrays"
        ),
        agent=agents["analyst"],
        output_json=AnalyzedFindings,
    )

    report = Task(
        description=(
            "Write the final markdown report from the analyst's evaluated findings.\n\n"
            "You receive the analyst's claims as context: each claim has supporting "
            "sources (citation ids, URLs, titles, relevance), an evidence strength "
            "category (high / moderate / low / insufficient / conflicted), "
            "limitations, and any contradictions, plus research gaps and an overall "
            "confidence.\n\n"
            "Report structure — include a section only when it is relevant to the "
            "findings:\n"
            "1. Title\n"
            "2. Executive Summary\n"
            "3. Introduction and Research Scope\n"
            "4. Key Findings\n"
            "5. Detailed Analysis\n"
            "6. Evidence and Supporting Sources\n"
            "7. Conflicting Findings\n"
            "8. Limitations and Uncertainties\n"
            "9. Research Gaps\n"
            "10. Conclusion\n"
            "11. References\n\n"
            "Do not force irrelevant sections into every report. Maintain logical "
            "progression. Use meaningful headings. Keep paragraphs focused. Avoid "
            "repeating the executive summary in the introduction.\n\n"
            "Citation reliability (mandatory):\n"
            "- Every factual claim requiring external support must carry an inline "
            "citation [^n] matching a source in the analyst's findings.\n"
            "- Citation identifiers refer only to sources actually retrieved. Never "
            "invent a citation id, URL, title, author, or publication date.\n"
            "- Never cite a source that does not support the associated claim.\n"
            "- Place citations close to the claims they support; avoid one citation "
            "covering a paragraph of unrelated claims.\n"
            "- Preserve the citation numbering [^1], [^2], ... as assigned; do not "
            "renumber.\n"
            "- If a claim has insufficient evidence, state that plainly instead of "
            "manufacturing a citation.\n\n"
            "Evidence and uncertainty:\n"
            "- Preserve the analyst's evidence-strength categories. Do not upgrade "
            "weak evidence into definitive statements.\n"
            "- Represent conflicting findings fairly; explain when evidence cannot "
            "resolve a disagreement.\n"
            "- Distinguish an unanswered research question from a negative finding.\n"
            "- Preserve claim limitations; do not override the evidence assessment.\n\n"
            "Executive Summary:\n"
            "- Directly answer the research question where evidence permits.\n"
            "- Highlight the most important findings.\n"
            "- Mention significant uncertainty or disagreement.\n"
            "- Stay concise: two to three paragraphs. No generic summary.\n\n"
            "References:\n"
            "- List every cited source once: title, original URL, publication date "
            "(if known), source category (heuristic), retrieval date.\n"
            "- Do not fabricate missing metadata. Do not list uncited sources.\n"
            "- Do not present heuristic source categories as verified authority.\n\n"
            "Readability:\n"
            "- Avoid repetitive paragraphs, generic introductions, citation dumps "
            "without context, and repeating the same claim in multiple sections.\n"
            "- Write for a technical decision-maker: precise, scannable, actionable."
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
