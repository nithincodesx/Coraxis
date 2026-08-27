"""
Task Definitions — Sequential CrewAI task chain with Pydantic output schemas.
Researcher → Web Searcher → Analyst → Summarizer
"""

from typing import Optional
from crewai import Task, Process, Crew
from pydantic import BaseModel, Field, field_validator

from agents import create_agents, AgentFactory
from utils.llm_factory import get_available_providers


# ─── Pydantic Output Schemas ───

class SubQuestions(BaseModel):
    """Researcher output: decomposed sub-questions."""
    sub_questions: list[str] = Field(
        default_factory=list,
        min_length=3,
        max_length=8,
        description="Specific, searchable sub-questions covering key angles of the topic"
    )
    key_entities: list[str] = Field(
        default_factory=list,
        description="Important entities, people, organizations, or concepts to search for"
    )
    search_strategy: str = Field(
        default="",
        description="Brief rationale for the decomposition approach"
    )

    @field_validator("sub_questions")
    @classmethod
    def validate_questions(cls, v: list[str]) -> list[str]:
        # Ensure questions end with ? and are substantial
        cleaned = [q.strip().rstrip("?") + "?" for q in v if q.strip()]
        return cleaned[:8]


class RawFindings(BaseModel):
    """Web Searcher output: raw search results per sub-question."""
    findings: list["FindingItem"] = Field(default_factory=list)
    total_sources: int = 0
    search_time_seconds: float = 0.0


class FindingItem(BaseModel):
    question: str = Field(description="The sub-question this finding addresses")
    url: str = Field(description="Source URL")
    title: str = Field(description="Page title")
    snippet: str = Field(description="Search snippet")
    full_text: str = Field(default="", description="Full extracted page text")
    word_count: int = 0
    fetch_success: bool = False


class AnalyzedFindings(BaseModel):
    """Analyst output: synthesized claims with confidence and relevance."""
    claims: list["Claim"] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list, description="Noted contradictions between sources")
    gaps: list[str] = Field(default_factory=list, description="Identified information gaps")
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class Claim(BaseModel):
    claim_id: str = Field(description="Unique identifier for this claim")
    text: str = Field(description="The claim statement")
    supporting_sources: list["SourceRef"] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, description="Analyst's confidence in this claim")
    relevance: float = Field(ge=0.0, le=1.0, description="Overall relevance of supporting sources")
    agent: str = Field(default="analyst")


class SourceRef(BaseModel):
    url: str
    title: str
    relevance: float = Field(ge=0.0, le=1.0, description="Relevance of this source to the claim")
    snippet: str = ""


class FinalReport(BaseModel):
    """Summarizer output: complete markdown report."""
    markdown: str = Field(description="Full report in markdown with inline citations [^n]")
    executive_summary: str = Field(description="2-3 paragraph executive summary")
    key_findings: list[str] = Field(default_factory=list, description="Bullet-point key findings")
    citations_markdown: str = Field(description="Formatted references section")
    stats: "ReportStats" = Field(default_factory=lambda: ReportStats())


class ReportStats(BaseModel):
    total_sources: int = 0
    total_claims: int = 0
    avg_confidence: float = 0.0
    avg_relevance: float = 0.0
    agents_used: list[str] = Field(default_factory=list)
    models_used: dict[str, str] = Field(default_factory=dict)
    runtime_seconds: float = 0.0


# ─── Task Creation ───

def create_tasks(factory: AgentFactory) -> list[Task]:
    """
    Create the four sequential tasks bound to their respective agents.
    
    Args:
        factory: Configured AgentFactory instance.
        
    Returns:
        List of 4 sequential CrewAI Tasks.
    """

    # Task 1: Decompose query into sub-questions
    decompose_task = Task(
        description=(
            "Analyze the user's research query: '{query}'.\n\n"
            "1. Break it down into 4-7 specific, searchable sub-questions that cover all key angles.\n"
            "2. Identify key entities (people, orgs, concepts, products) that should be searched.\n"
            "3. Check semantic memory for any prior findings on this topic using recall_memory tool.\n"
            "4. Output structured SubQuestions JSON.\n\n"
            "Be precise. Each sub-question should be answerable by a single web search."
        ),
        expected_output=(
            "JSON matching SubQuestions schema: "
            "{sub_questions: [...], key_entities: [...], search_strategy: '...'}"
        ),
        agent=factory.researcher,
        output_json=SubQuestions,
    )

    # Task 2: Search and fetch for each sub-question
    search_task = Task(
        description=(
            "For EACH sub-question from the previous step:\n"
            "1. Search DuckDuckGo (duckduckgo_search tool) for top 5-8 results.\n"
            "2. Fetch full page content (fetch_page tool) for top 3-5 results per question.\n"
            "3. Return structured RawFindings with all successful fetches.\n\n"
            "Prioritize authoritative sources: academic, official docs, reputable journalism, "
            "technical blogs. Skip paywalls, login walls, and low-quality aggregators."
        ),
        expected_output=(
            "JSON matching RawFindings schema with findings array containing "
            "question, url, title, snippet, full_text, word_count, fetch_success"
        ),
        agent=factory.web_searcher,
        output_json=RawFindings,
    )

    # Task 3: Analyze and synthesize
    analyze_task = Task(
        description=(
            "Analyze all raw findings from the web searcher:\n"
            "1. Cross-reference findings across sub-questions. Detect consensus and contradictions.\n"
            "2. For each distinct claim, identify supporting sources and score relevance (0-100%).\n"
            "3. Assign calibrated confidence (0-100%) to each claim based on:\n"
            "   - Number and quality of supporting sources\n"
            "   - Source agreement/disagreement\n"
            "   - Source authority and recency\n"
            "   - Specificity of evidence\n"
            "4. Note any conflicts between sources and information gaps.\n"
            "5. **IMPORTANT**: For each claim you synthesize, CALL the 'register_claim' tool to "
            "   formally record it in the citation tracker with its supporting sources, confidence, "
            "   and relevance scores. This enables proper citation generation in the final report.\n"
            "6. Output structured AnalyzedFindings JSON.\n\n"
            "Be rigorous. A claim with one blog post gets low confidence. "
            "A claim with 3 independent authoritative sources gets high confidence."
        ),
        expected_output=(
            "JSON matching AnalyzedFindings schema with claims array containing "
            "claim_id, text, supporting_sources[{url, title, relevance, snippet}], "
            "confidence, relevance, plus conflicts and gaps arrays"
        ),
        agent=factory.analyst,
        output_json=AnalyzedFindings,
    )

    # Task 4: Write final report
    report_task = Task(
        description=(
            "Write a polished, structured markdown report from the analyst's output:\n\n"
            "## Required Structure:\n"
            "1. **Executive Summary** (2-3 paragraphs, decision-maker ready)\n"
            "2. **Key Findings** (5-8 bullet points, each with inline citation [^n])\n"
            "3. **Detailed Findings** (sections per major theme, evidence-backed)\n"
            "4. **Confidence Assessment** (overall + per-claim if notable variance)\n"
            "5. **Sources Appendix** (formatted references with relevance scores)\n\n"
            "## Formatting Rules:\n"
            "- Inline citations: [^1], [^2] etc. referencing Sources Appendix\n"
            "- Use ### for section headers, #### for subsections\n"
            "- Bold key terms, use blockquotes for direct quotes\n"
            "- Include relevance scores in Sources Appendix\n"
            "- Write for a technical decision-maker: precise, scannable, actionable\n\n"
            "## Sources:\n"
            "Use the citation tracker's formatted markdown for the Sources section. "
            "The tracker will provide properly formatted references with relevance bars.\n\n"
            "## Output:\n"
            "JSON matching FinalReport schema with markdown, executive_summary, "
            "key_findings, citations_markdown, and stats."
        ),
        expected_output=(
            "JSON matching FinalReport schema with complete markdown report, "
            "executive summary, key findings list, citations markdown, and stats"
        ),
        agent=factory.summarizer,
        output_json=FinalReport,
    )

    return [decompose_task, search_task, analyze_task, report_task]


def create_crew(
    use_global_key: bool = False,
    global_key: str = "",
    tracker=None,
    callbacks=None,
) -> Crew:
    """Create the full CrewAI crew with sequential process."""
    from agents import AgentFactory
    factory = AgentFactory(use_global_key=use_global_key, global_key=global_key, tracker=tracker)
    factory.create_all()
    tasks = create_tasks(factory)

    crew = Crew(
        agents=[factory.researcher, factory.web_searcher, factory.analyst, factory.summarizer],
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
        memory=False,  # We use our own ChromaDB memory
        max_rpm=10,  # Rate limit for free tiers
        callbacks=callbacks if callbacks else [],
    )
    return crew


# ─── Convenience: Run Research ───

async def run_research(
    query: str,
    use_global_key: bool = False,
    global_key: str = "",
    progress_callback=None,
    tracker=None,
    callbacks=None,
) -> FinalReport:
    """
    Run the full research pipeline.
    Returns FinalReport with markdown and metadata.
    """
    import time
    start = time.time()

    crew = create_crew(
        use_global_key=use_global_key,
        global_key=global_key,
        tracker=tracker,
        callbacks=callbacks,
    )

    # Kick off with progress tracking
    result = crew.kickoff(inputs={"query": query})

    runtime = time.time() - start

    # Parse result (CrewAI returns the last task's output)
    if isinstance(result, FinalReport):
        report = result
    else:
        # Try to parse from raw output
        import json
        try:
            report = FinalReport.model_validate_json(result.raw if hasattr(result, 'raw') else str(result))
        except Exception:
            # Fallback: construct minimal report
            report = FinalReport(
                markdown=str(result),
                executive_summary="Report generation completed.",
                key_findings=[],
                citations_markdown="",
                stats=ReportStats(runtime_seconds=runtime),
            )

    report.stats.runtime_seconds = runtime
    return report