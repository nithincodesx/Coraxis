"""Run submission, lifecycle, quotas, and cross-account isolation.

Runs are not executed here. The real runner schedules an asyncio task, which
would make the tests depend on an LLM and on timing; instead a recording double
captures submissions and each test drives the run to a terminal state itself.
That keeps the assertions deterministic while still exercising the real routes,
repositories and serialisation.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

QUERY = "How does retrieval augmented generation reduce hallucination?"


class _RecordingRunner:
    """Captures submissions instead of executing them."""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.accepting = True

    def submit(self, run_id: str) -> bool:
        if not self.accepting:
            return False
        self.submitted.append(run_id)
        return True


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> _RecordingRunner:
    """Swap the process-wide runner for a recording double.

    The endpoint binds the runner by name at import time, so patching the
    endpoint module's reference is what actually takes effect.
    """
    from coraxis.api.v1.endpoints import runs as runs_endpoint

    double = _RecordingRunner()
    monkeypatch.setattr(runs_endpoint, "run_runner", double)
    return double


#: Which terminal event each status emits, mirroring the orchestrator.
_TERMINAL_EVENT = {
    "succeeded": "RUN_SUCCEEDED",
    "failed": "RUN_FAILED",
    "cancelled": "RUN_CANCELLED",
    "timed_out": "RUN_TIMED_OUT",
}


async def _drive(
    run_id: str,
    *,
    status: str = "succeeded",
    report: str = "",
    error: str = "",
) -> None:
    """Move a run to a terminal state the way the orchestrator would.

    Emits the same event sequence the real run does — queued, started, terminal
    — because the event timeline is a product surface, not incidental logging.
    """
    from coraxis.db import enums
    from coraxis.db.session import session_scope
    from coraxis.repositories import runs as run_repo

    async with session_scope() as session:
        run = await run_repo.get_run_unscoped(session, run_id)
        assert run is not None, f"run {run_id} vanished"

        await run_repo.mark_started(session, run)
        await run_repo.add_event(
            session,
            run_id,
            type=enums.EventType.RUN_STARTED,
            message="Pipeline started",
        )

        if report:
            await run_repo.attach_report(
                session,
                run,
                report_markdown=report,
                executive_summary="A summary.",
                key_findings=["Finding one"],
                citations_markdown="### Sources",
                stats={"total_sources": 3, "total_claims": 2, "avg_confidence": 0.8},
            )
            await run_repo.add_event(
                session,
                run_id,
                type=enums.EventType.REPORT_READY,
                message="Report assembled",
            )

        terminal = getattr(enums.EventType, _TERMINAL_EVENT[status])
        await run_repo.add_event(
            session,
            run_id,
            type=terminal,
            level=(enums.EventLevel.SUCCESS if status == "succeeded" else enums.EventLevel.ERROR),
            message=error or f"Run {status}",
        )
        await run_repo.mark_finished(session, run, status=enums.RunStatus(status), error=error)


async def _submit(auth_client: AsyncClient, query: str = QUERY) -> dict:
    response = await auth_client.post("/api/v1/runs", json={"query": query})
    assert response.status_code == 202, response.text
    return response.json()


# ─── Submission ──────────────────────────────────────────────────────


async def test_submitting_a_run_returns_202_and_hands_it_to_the_runner(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    body = await _submit(auth_client)

    assert body["status"] == "queued"
    assert body["stream_url"] == f"/api/v1/runs/{body['run_id']}/stream"
    assert body["detail_url"] == f"/api/v1/runs/{body['run_id']}"
    assert runner.submitted == [body["run_id"]]


async def test_a_one_word_query_is_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.post("/api/v1/runs", json={"query": "hi"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_an_unknown_option_is_rejected_rather_than_ignored(
    auth_client: AsyncClient,
) -> None:
    """Request models forbid extras, so a typo'd option fails loudly."""
    response = await auth_client.post(
        "/api/v1/runs", json={"query": QUERY, "options": {"max_soruces": 5}}
    )
    assert response.status_code == 422


# ─── Reading ─────────────────────────────────────────────────────────


async def test_a_run_appears_in_the_list_with_a_page_envelope(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)

    response = await auth_client.get("/api/v1/runs")
    assert response.status_code == 200
    page = response.json()

    assert set(page) == {"items", "total", "limit", "offset"}
    assert page["total"] == 1
    assert page["items"][0]["id"] == submitted["run_id"]


async def test_the_list_can_be_filtered_by_status(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], status="succeeded")

    completed = await auth_client.get("/api/v1/runs", params={"status": "succeeded"})
    assert [item["id"] for item in completed.json()["items"]] == [submitted["run_id"]]

    queued = await auth_client.get("/api/v1/runs", params={"status": "queued"})
    assert queued.json()["items"] == []


async def test_an_unknown_run_is_a_404(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/runs/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_a_finished_run_reports_its_report_and_stats(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], report="# Findings\n\nBody text.")

    response = await auth_client.get(f"/api/v1/runs/{submitted['run_id']}")
    assert response.status_code == 200
    detail = response.json()

    assert detail["status"] == "succeeded"
    assert detail["report_markdown"].startswith("# Findings")
    assert detail["stats"]["total_sources"] == 3
    assert detail["source_count"] == 3
    assert detail["key_findings"] == ["Finding one"]
    assert detail["finished_at"] is not None
    assert detail["runtime_seconds"] >= 0


async def test_the_report_downloads_as_markdown(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], report="# Downloadable")

    response = await auth_client.get(f"/api/v1/runs/{submitted['run_id']}/report.md")
    assert response.status_code == 200
    assert response.text == "# Downloadable"
    assert "attachment" in response.headers["content-disposition"]


async def test_downloading_a_report_that_does_not_exist_yet_is_a_404(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    response = await auth_client.get(f"/api/v1/runs/{submitted['run_id']}/report.md")
    assert response.status_code == 404


# ─── Events ──────────────────────────────────────────────────────────


async def test_events_carry_a_monotonic_sequence(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    """The sequence is the resume cursor, so gaps or repeats would break replay."""
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], report="# Done")

    response = await auth_client.get(f"/api/v1/runs/{submitted['run_id']}/events")
    assert response.status_code == 200
    events = response.json()
    assert events, "a submitted run must record at least one event"

    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "sequence numbers must be unique"
    assert seqs[0] >= 1


async def test_the_since_parameter_returns_only_newer_events(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], report="# Done")
    run_id = submitted["run_id"]

    everything = (await auth_client.get(f"/api/v1/runs/{run_id}/events")).json()
    assert len(everything) >= 2, "need at least two events for this to be meaningful"

    cutoff = everything[0]["seq"]
    tail = (await auth_client.get(f"/api/v1/runs/{run_id}/events", params={"since": cutoff})).json()

    assert tail == [event for event in everything if event["seq"] > cutoff]
    assert all(event["seq"] > cutoff for event in tail)


# ─── Cancellation, retry, deletion ───────────────────────────────────


async def test_cancelling_a_running_run_sets_the_flag(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    response = await auth_client.post(f"/api/v1/runs/{submitted['run_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    from coraxis.db.session import session_scope
    from coraxis.repositories import runs as run_repo

    async with session_scope() as session:
        assert await run_repo.is_cancel_requested(session, submitted["run_id"]) is True


async def test_cancelling_a_finished_run_is_a_no_op(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    """Honest reporting: a finished run cannot be un-finished."""
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], status="succeeded")

    response = await auth_client.post(f"/api/v1/runs/{submitted['run_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


async def test_retrying_creates_a_new_run_with_the_same_query(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    await _drive(submitted["run_id"], status="failed", error="provider exploded")

    response = await auth_client.post(f"/api/v1/runs/{submitted['run_id']}/retry")
    assert response.status_code == 202, response.text

    retried = response.json()
    assert retried["run_id"] != submitted["run_id"]

    detail = (await auth_client.get(f"/api/v1/runs/{retried['run_id']}")).json()
    assert detail["query"] == QUERY
    assert detail["trigger"] == "retry"
    assert runner.submitted == [submitted["run_id"], retried["run_id"]]


async def test_retrying_an_unfinished_run_is_refused(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    response = await auth_client.post(f"/api/v1/runs/{submitted['run_id']}/retry")
    assert response.status_code == 429


async def test_deleting_a_run_removes_it(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)
    run_id = submitted["run_id"]

    response = await auth_client.delete(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    assert (await auth_client.get(f"/api/v1/runs/{run_id}")).status_code == 404
    assert (await auth_client.get("/api/v1/runs")).json()["total"] == 0


# ─── Quotas and isolation ────────────────────────────────────────────


async def test_concurrent_runs_are_capped_per_user(
    auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    """The cap is what stops one account from monopolising the worker pool."""
    from coraxis.core.config import get_settings

    limit = get_settings().run_max_concurrent_per_user
    for _ in range(limit):
        await _submit(auth_client)

    overflow = await auth_client.post("/api/v1/runs", json={"query": QUERY})
    assert overflow.status_code == 429
    assert overflow.headers["content-type"].startswith("application/problem+json")
    assert overflow.json()["active_runs"] == limit


async def test_one_account_cannot_read_another_accounts_run(
    client: AsyncClient, auth_client: AsyncClient, runner: _RecordingRunner
) -> None:
    submitted = await _submit(auth_client)

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "intruder@example.com",
            "password": "an-entirely-different-passphrase",
            "display_name": "Intruder",
        },
    )
    assert second.status_code == 201, second.text
    headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    run_id = submitted["run_id"]

    # Every route that takes a run id must scope it to the caller.
    assert (await client.get(f"/api/v1/runs/{run_id}", headers=headers)).status_code == 404
    assert (await client.get(f"/api/v1/runs/{run_id}/events", headers=headers)).status_code == 404
    assert (await client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)).status_code == 404
    assert (await client.delete(f"/api/v1/runs/{run_id}", headers=headers)).status_code == 404

    # And the run is untouched.
    assert (await auth_client.get(f"/api/v1/runs/{run_id}")).status_code == 200
