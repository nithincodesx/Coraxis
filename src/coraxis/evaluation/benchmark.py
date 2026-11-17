"""Fixed research benchmark for Phase 02.

A benchmark question is a research request together with the criteria a good
answer should satisfy. The same list is executed before and after every
intelligence improvement so that regressions and gains are measurable.

The questions are representative, not exhaustive: they are chosen to exercise
different failure modes of the pipeline (multi-part decomposition, conflicting
sources, insufficient evidence, time sensitivity, primary-source requirements)
rather than to cover the whole research domain.

Do not fabricate expected answers. Where a question genuinely has no settled
answer, that is part of the test: the system should report uncertainty rather
than invent one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkQuestion:
    """One fixed research case used to measure pipeline quality."""

    id: str
    question: str
    category: str
    expected_coverage: list[str]
    subquestions: list[str]
    expected_evidence_types: list[str]
    authoritative_sources: list[str]
    common_failure_modes: list[str]
    evaluation_criteria: list[str]
    time_sensitive: bool = False
    benchmark_date: str | None = None


#: The fixed benchmark. Ten questions, eight categories.
#:
#: Categories:
#:   factual — verifiable facts with clear answers
#:   technical — domain-specific technical claims
#:   comparative — two or more alternatives to weigh
#:   multipart — several distinct information needs in one question
#:   conflicting — sources disagree; system must not pick a side silently
#:   time-sensitive — answer depends on publication date / freshness
#:   primary-source — requires official or original documentation
#:   insufficient-evidence — genuinely unsettled; system should say so
BENCHMARK: list[BenchmarkQuestion] = [
    BenchmarkQuestion(
        id="bench-001",
        question="What are the main differences between SQLite and PostgreSQL, and when should a new application choose one over the other?",
        category="comparative",
        expected_coverage=[
            "architecture differences (serverless vs client-server)",
            "concurrency and write handling",
            "data types and type strictness",
            "operational overhead and hosting",
            "when to choose each",
        ],
        subquestions=[
            "How does SQLite's architecture differ from PostgreSQL's?",
            "What are the concurrency limitations of SQLite?",
            "When is PostgreSQL preferable to SQLite for a new application?",
            "What operational overhead does each database require?",
        ],
        expected_evidence_types=[
            "official documentation",
            "technical comparison",
            "benchmark data",
        ],
        authoritative_sources=[
            "https://sqlite.org/",
            "https://www.postgresql.org/",
        ],
        common_failure_modes=[
            "Picks one database without explaining trade-offs",
            "Cites only blog posts, not official docs",
            "Ignores concurrency or operational differences",
        ],
        evaluation_criteria=[
            "Both databases are covered with concrete differences",
            "A clear decision framework is provided",
            "Sources include official documentation for both",
        ],
    ),
    BenchmarkQuestion(
        id="bench-002",
        question="How does retrieval-augmented generation (RAG) reduce hallucination in large language models?",
        category="technical",
        expected_coverage=[
            "Definition of RAG",
            "Mechanism by which grounding reduces hallucination",
            "Limitations — RAG does not eliminate hallucination entirely",
        ],
        subquestions=[
            "What is retrieval-augmented generation?",
            "How does providing retrieved context reduce hallucination?",
            "What failure modes remain when using RAG?",
        ],
        expected_evidence_types=[
            "research paper",
            "technical explanation",
            "official documentation",
        ],
        authoritative_sources=[
            "https://arxiv.org/",
            "https://platform.openai.com/",
        ],
        common_failure_modes=[
            "Claims RAG eliminates hallucination entirely",
            "No citation to the original RAG paper (Lewis et al., 2020)",
            "Confuses fine-tuning with RAG",
        ],
        evaluation_criteria=[
            "Explains the grounding mechanism accurately",
            "Acknowledges remaining limitations",
            "Cites the original RAG paper or equivalent authoritative source",
        ],
    ),
    BenchmarkQuestion(
        id="bench-003",
        question="Is creatine monohydrate supplementation safe and effective for healthy adults, and what dosage is commonly recommended?",
        category="factual",
        expected_coverage=[
            "Safety profile for healthy adults",
            "Effectiveness for performance/muscle outcomes",
            "Commonly recommended dosage",
            "Any well-documented side effects",
        ],
        subquestions=[
            "Is creatine monohydrate safe for healthy adults?",
            "What performance benefits does creatine monohydrate have?",
            "What dosage is commonly recommended?",
            "What side effects are documented?",
        ],
        expected_evidence_types=["systematic review", "meta-analysis", "position stand"],
        authoritative_sources=[
            "https://pubmed.ncbi.nlm.nih.gov/",
            "https://www.ncbi.nlm.nih.gov/",
        ],
        common_failure_modes=[
            "Gives medical advice without qualifying it",
            "Cites supplement vendor pages as authoritative",
            "Omits dosage entirely",
        ],
        evaluation_criteria=[
            "States safety and effectiveness with appropriate caveats",
            "Provides a specific dosage range",
            "Distinguishes evidence quality (meta-analysis vs anecdote)",
        ],
    ),
    BenchmarkQuestion(
        id="bench-004",
        question="Compare the carbon footprint of electric vehicles versus internal combustion engine vehicles over their full lifecycle, including manufacturing.",
        category="comparative",
        expected_coverage=[
            "Manufacturing emissions (especially battery production)",
            "Operational emissions",
            "End-of-life/recycling",
            "Break-even mileage or timeframe",
        ],
        subquestions=[
            "How do manufacturing emissions compare between EVs and ICE vehicles?",
            "How do operational emissions compare?",
            "At what mileage does an EV's lower operational emissions offset its higher manufacturing emissions?",
            "How are end-of-life and recycling handled?",
        ],
        expected_evidence_types=[
            "lifecycle assessment study",
            "government report",
            "peer-reviewed analysis",
        ],
        authoritative_sources=[
            "https://www.epa.gov/",
            "https://www.iea.org/",
        ],
        common_failure_modes=[
            "Ignores manufacturing emissions entirely",
            "Claims EVs are zero-emission without qualification",
            "No break-even analysis",
        ],
        evaluation_criteria=[
            "Covers full lifecycle, not just tailpipe emissions",
            "Provides a break-even estimate with caveats",
            "Cites lifecycle assessment sources",
        ],
    ),
    BenchmarkQuestion(
        id="bench-005",
        question="What were the key announcements at Apple's WWDC 2024, and which were available at launch versus later in the year?",
        category="time-sensitive",
        expected_coverage=[
            "Major software announcements (iOS 18, macOS, etc.)",
            "Apple Intelligence features",
            "Availability timeline for each announcement",
        ],
        subquestions=[
            "What operating system updates were announced at WWDC 2024?",
            "What is Apple Intelligence and which devices support it?",
            "Which announcements shipped at launch versus later?",
        ],
        expected_evidence_types=["press release", "official documentation", "news coverage"],
        authoritative_sources=[
            "https://www.apple.com/newsroom/",
            "https://developer.apple.com/",
        ],
        common_failure_modes=[
            "Confuses WWDC 2024 with WWDC 2023 or 2025",
            "States everything was available immediately",
            "Omits Apple Intelligence entirely",
        ],
        evaluation_criteria=[
            "Correctly identifies WWDC 2024 (June 2024)",
            "Distinguishes launch vs later availability",
            "Sources are dated around the event",
        ],
        time_sensitive=True,
        benchmark_date="2026-11-10",
    ),
    BenchmarkQuestion(
        id="bench-006",
        question="What is the current status of the EU AI Act, and which provisions apply to general-purpose AI models?",
        category="time-sensitive",
        expected_coverage=[
            "Legislative status (adopted, in force, etc.)",
            "Timeline of application",
            "Provisions specific to general-purpose AI models",
            "Obligations for providers of such models",
        ],
        subquestions=[
            "What is the current legal status of the EU AI Act?",
            "When do its provisions take effect?",
            "Which rules apply specifically to general-purpose AI models?",
            "What obligations do general-purpose AI model providers face?",
        ],
        expected_evidence_types=["official EU legislation", "EU Commission page", "legal analysis"],
        authoritative_sources=[
            "https://eur-lex.europa.eu/",
            "https://commission.europa.eu/",
        ],
        common_failure_modes=[
            "States the Act is still a proposal",
            "Confuses the AI Act with the GDPR",
            "Omits general-purpose AI provisions",
        ],
        evaluation_criteria=[
            "Correctly states adoption and entry-into-force dates",
            "Identifies general-purpose AI model provisions specifically",
            "Sources are official EU sources",
        ],
        time_sensitive=True,
        benchmark_date="2026-11-10",
    ),
    BenchmarkQuestion(
        id="bench-007",
        question="Does the European Union's General Data Protection Regulation (GDPR) apply to a US-based website that has no physical presence in the EU but offers goods to EU customers?",
        category="primary-source",
        expected_coverage=[
            "Territorial scope of GDPR (Article 3)",
            "Criteria for applying to non-EU organizations",
            "Offering goods/services to EU data subjects",
        ],
        subquestions=[
            "What does GDPR Article 3 say about territorial scope?",
            "Does offering goods to EU customers trigger GDPR for a US company?",
            "What conditions must be met for GDPR to apply extraterritorially?",
        ],
        expected_evidence_types=["regulation text", "official EU guidance", "legal commentary"],
        authoritative_sources=[
            "https://eur-lex.europa.eu/",
            "https://gdpr.eu/",
        ],
        common_failure_modes=[
            "Says GDPR only applies to EU-based companies",
            "Omits Article 3 entirely",
            "Gives a definitive yes/no without legal caveat",
        ],
        evaluation_criteria=[
            "Cites Article 3 territorial scope",
            "Explains the offering-goods criterion",
            "Distinguishes law from legal advice",
        ],
    ),
    BenchmarkQuestion(
        id="bench-008",
        question="What are the leading explanations for the Fermi paradox, and which is most widely accepted among astrobiologists?",
        category="multipart",
        expected_coverage=[
            "Definition of the Fermi paradox",
            "At least three distinct proposed explanations",
            "Assessment of consensus / which is most accepted",
        ],
        subquestions=[
            "What is the Fermi paradox?",
            "What are the leading proposed explanations?",
            "Is there a consensus among astrobiologists on any explanation?",
        ],
        expected_evidence_types=["scientific paper", "review article", "institutional page"],
        authoritative_sources=[
            "https://www.nasa.gov/",
            "https://arxiv.org/",
        ],
        common_failure_modes=[
            "Picks one explanation as fact rather than hypothesis",
            "Omits the Great Filter hypothesis",
            "Claims a consensus that does not exist",
        ],
        evaluation_criteria=[
            "Presents multiple explanations as hypotheses, not facts",
            "Notes that no single explanation is consensus",
            "Cites scientific sources",
        ],
    ),
    BenchmarkQuestion(
        id="bench-009",
        question="What are the arguments for and against universal basic income, and what evidence exists from pilot programs?",
        category="conflicting",
        expected_coverage=[
            "Arguments in favor of UBI",
            "Arguments against UBI",
            "Evidence from at least one pilot program",
            "Limitations of that evidence",
        ],
        subquestions=[
            "What are the main arguments for universal basic income?",
            "What are the main arguments against universal basic income?",
            "What have UBI pilot programs found?",
            "What are the limitations of pilot-program evidence?",
        ],
        expected_evidence_types=["pilot program report", "economic analysis", "policy paper"],
        authoritative_sources=[
            "https://www.oecd.org/",
            "https://www.worldbank.org/",
        ],
        common_failure_modes=[
            "Presents only one side of the debate",
            "Cites advocacy group pages as neutral evidence",
            "Overstates pilot program results",
        ],
        evaluation_criteria=[
            "Presents both for and against arguments fairly",
            "References specific pilot programs",
            "Acknowledges evidence limitations",
        ],
    ),
    BenchmarkQuestion(
        id="bench-010",
        question="Who won the 2026 FIFA World Cup, and what was the final score?",
        category="insufficient-evidence",
        expected_coverage=[
            "Honest statement that the event has not occurred / result is unknown",
            "Explanation that this is a future event",
        ],
        subquestions=[
            "When is the 2026 FIFA World Cup scheduled?",
            "Has the 2026 FIFA World Cup taken place yet?",
        ],
        expected_evidence_types=["official FIFA announcement", "sports news"],
        authoritative_sources=[
            "https://www.fifa.com/",
        ],
        common_failure_modes=[
            "Invents a winner and score",
            "Confuses with the 2022 World Cup",
            "Pretends to know an unknowable result",
        ],
        evaluation_criteria=[
            "States plainly that the result is not yet known",
            "Does not invent a winner or score",
            "References the tournament schedule",
        ],
        time_sensitive=True,
        benchmark_date="2026-11-10",
    ),
]


def find_benchmark_question(question_id: str) -> BenchmarkQuestion | None:
    """Look up one benchmark question by id."""
    for question in BENCHMARK:
        if question.id == question_id:
            return question
    return None


def benchmark_by_category(category: str) -> list[BenchmarkQuestion]:
    """All benchmark questions in one category."""
    return [question for question in BENCHMARK if question.category == category]


def categories() -> list[str]:
    """Distinct benchmark categories in first-seen order."""
    seen: list[str] = []
    for question in BENCHMARK:
        if question.category not in seen:
            seen.append(question.category)
    return seen


def to_dict(question: BenchmarkQuestion) -> dict[str, Any]:
    """Serialise a benchmark question for storage or reporting."""
    return {
        "id": question.id,
        "question": question.question,
        "category": question.category,
        "expected_coverage": question.expected_coverage,
        "subquestions": question.subquestions,
        "expected_evidence_types": question.expected_evidence_types,
        "authoritative_sources": question.authoritative_sources,
        "common_failure_modes": question.common_failure_modes,
        "evaluation_criteria": question.evaluation_criteria,
        "time_sensitive": question.time_sensitive,
        "benchmark_date": question.benchmark_date,
    }
