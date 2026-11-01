"""Spend safety net: caps, per-run attribution, loop bounds, idempotency, startup recovery.
Fake LLM or mocked SDK only — never a real OpenAI call."""
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.core.db as db
from app.core.config import settings
from app.core.db import engine
from app.llm import get_llm, set_llm
from app.llm.base import LLMBudgetExceeded, llm_run_scope
from app.llm.openai_client import OpenAIClient
from app.models import Project, Run, RunStatus
from app.models.tables import LLMCall, utcnow
from app.schemas import DashboardIssue, SanityIssue, SanityReport
from app.services import orchestrator as orch
from app.services.locks import ProjectBusy, project_lock
from tests.test_e2e_api import CSV, _wait, client  # noqa: F401  (fixture)
from tests.test_llm_openai import MockCompletions, _parsed, make_client


class Answer(BaseModel):
    value: int


def _text_resp(content: str, prompt_tokens: int = 100, completion_tokens: int = 20):
    return NS(choices=[NS(message=NS(content=content, tool_calls=None), finish_reason="stop")],
              usage=NS(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))


@pytest.fixture
def mem_db(monkeypatch):
    """Isolated llm_calls table for the client-level tests (budget + logging read app.core.db.engine)."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db, "engine", eng)
    return eng


def _add_calls(eng, n: int = 1, cost: float = 0.0, project_id: int | None = 1, run_id: int | None = None,
               days_ago: int = 0) -> None:
    with Session(eng) as s:
        for _ in range(n):
            s.add(LLMCall(project_id=project_id, run_id=run_id, agent="t", cost=cost,
                          created_at=utcnow() - timedelta(days=days_ago)))
        s.commit()


# ---------------------------------------------------------------- client-level caps

def test_max_completion_tokens_passed(mem_db, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_output_tokens", 8000)
    monkeypatch.setattr(settings, "llm_max_output_tokens_other", 3000)
    comp = MockCompletions(create_results=[_text_resp("x"), _text_resp("y")],
                           parse_results=[_parsed(Answer(value=1))])
    c = make_client(comp)
    c.text(agent="coder", system="", user="")
    c.text(agent="insights", system="", user="")
    c.structured(agent="planner", system="", user="", schema=Answer)
    assert [k["max_completion_tokens"] for k in comp.create_calls] == [8000, 3000]
    assert comp.parse_calls[0]["max_completion_tokens"] == 3000


@pytest.mark.parametrize("cap,value,setup,match", [
    ("llm_daily_budget_usd", 1.0, dict(n=2, cost=0.5, project_id=None), "daily budget"),
    ("llm_max_cost_per_project_usd", 1.0, dict(n=1, cost=1.0, project_id=1), "per-project cost"),
    ("llm_max_calls_per_project", 3, dict(n=3, cost=0.0, project_id=1), "calls for project 1"),
    ("llm_max_cost_per_run_usd", 0.2, dict(n=1, cost=0.25, project_id=1, run_id=7), "per-run cost for run 7"),
])
def test_caps_block_request(mem_db, monkeypatch, cap, value, setup, match):
    monkeypatch.setattr(settings, cap, value)
    _add_calls(mem_db, **setup)
    comp = MockCompletions(create_results=[_text_resp("never")])
    with llm_run_scope(7), pytest.raises(LLMBudgetExceeded, match=match) as exc:
        make_client(comp).text(agent="coder", system="", user="", project_id=1)
    assert comp.create_calls == []  # the request was never sent
    assert "backend/.env" in str(exc.value)


def test_caps_scope(mem_db, monkeypatch):
    """Yesterday's spend, other projects and other runs don't count."""
    monkeypatch.setattr(settings, "llm_daily_budget_usd", 1.0)
    monkeypatch.setattr(settings, "llm_max_cost_per_project_usd", 1.0)
    monkeypatch.setattr(settings, "llm_max_cost_per_run_usd", 0.5)
    _add_calls(mem_db, cost=5.0, project_id=1, days_ago=2)
    _add_calls(mem_db, cost=0.6, project_id=2, run_id=8)
    comp = MockCompletions(create_results=[_text_resp("ok")])
    with llm_run_scope(9):
        assert make_client(comp).text(agent="coder", system="", user="", project_id=3) == "ok"


def test_run_attribution_and_logging(mem_db, monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "gpt-4.1-mini")
    comp = MockCompletions(create_results=[_text_resp("a", 1_000_000, 0), _text_resp("b")])
    c = make_client(comp)
    with llm_run_scope(42):
        c.text(agent="coder", system="", user="", project_id=5)
    c.text(agent="analyst", system="", user="", project_id=5)  # outside a run
    with Session(mem_db) as s:
        rows = s.exec(select(LLMCall).order_by(LLMCall.id)).all()
    assert [(r.run_id, r.project_id) for r in rows] == [(42, 5), (None, 5)]
    assert rows[0].cost == pytest.approx(0.40)


def test_prompt_size_cap(mem_db, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_input_chars", 1000)
    comp = MockCompletions(create_results=[_text_resp("never")])
    with pytest.raises(LLMBudgetExceeded, match="LLM_MAX_INPUT_CHARS"):
        make_client(comp).text(agent="coder", system="", user="x" * 1001)
    assert comp.create_calls == []


def test_images_capped(mem_db, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_images", 2)
    monkeypatch.setattr(settings, "llm_vision_detail", "low")
    comp = MockCompletions(parse_results=[_parsed(Answer(value=1))])
    make_client(comp).structured(agent="qa", system="", user="u", schema=Answer, images=[b"png"] * 5)
    parts = comp.parse_calls[0]["messages"][1]["content"]
    assert len(parts) == 3 and parts[1]["image_url"]["detail"] == "low"


def _tool_step(n_calls: int = 1):
    return NS(choices=[NS(message=NS(content=None, tool_calls=[
        NS(id=str(i), function=NS(name="big", arguments="{}")) for i in range(n_calls)]))],
        usage=NS(prompt_tokens=1, completion_tokens=1))


def test_tool_loop_bounds(mem_db, monkeypatch):
    monkeypatch.setattr(settings, "llm_tool_max_steps", 3)
    monkeypatch.setattr(settings, "llm_tool_output_chars", 100)
    monkeypatch.setattr(settings, "llm_tool_max_calls_per_step", 2)
    tools = {"big": ({"type": "object", "properties": {}}, lambda: "x" * 500)}
    comp = MockCompletions(create_results=[_tool_step(4)] * 10, parse_results=[_parsed(Answer(value=0))])
    make_client(comp).tool_loop(agent="v", system="", user="", schema=Answer, tools=tools)  # max_steps=12
    assert len(comp.create_calls) == 3 and len(comp.parse_calls) == 1  # steps capped by settings, +1 answer
    outs = [m["content"] for m in comp.parse_calls[0]["messages"] if m["role"] == "tool"]
    assert len(outs[0]) < 150 and "truncated" in outs[0] and "skipped" in outs[2]

    monkeypatch.setattr(settings, "llm_tool_total_output_chars", 150)
    comp = MockCompletions(create_results=[_tool_step(2)] * 10, parse_results=[_parsed(Answer(value=0))])
    make_client(comp).tool_loop(agent="v", system="", user="", schema=Answer, tools=tools)
    assert len(comp.create_calls) == 1 and len(comp.parse_calls) == 1  # output budget used up → answer


def test_project_lock():
    with project_lock(1, "plan generation"):
        with pytest.raises(ProjectBusy, match="plan generation"):
            with project_lock(1, "validation"):
                pass
        with project_lock(2, "validation"):  # other projects are independent
            pass
    with project_lock(1, "validation"):  # released
        pass


# ---------------------------------------------------------------- end-to-end (API + orchestrator)

def _to_plan(c: TestClient) -> int:
    pid = c.post("/projects", json={"requirement": "Show revenue by month and region"}).json()["id"]
    assert c.post(f"/projects/{pid}/datasets", files=[("files", ("s.csv", CSV, "text/csv"))]).status_code == 200
    assert c.post(f"/projects/{pid}/validate").json()["status"] == "ready"
    assert c.post(f"/projects/{pid}/plan").status_code == 200
    return pid


def _agent_calls(fake, agent: str) -> int:
    return sum(1 for x in fake.calls if x["agent"] == agent)


def test_run_stops_at_run_budget(client: TestClient, monkeypatch):  # noqa: F811
    pid = _to_plan(client)
    monkeypatch.setattr(settings, "openai_model", "gpt-4.1-mini")
    monkeypatch.setattr(settings, "llm_max_cost_per_run_usd", 0.01)
    monkeypatch.setattr(settings, "llm_daily_budget_usd", 1000.0)
    monkeypatch.setattr(settings, "llm_max_cost_per_project_usd", 1000.0)
    # Broken code (static check rejects it → fix loop wants attempt 2), each call costs $0.40.
    comp = MockCompletions(create_results=[_text_resp("def run(:\n", 1_000_000, 0)] * 10)
    set_llm(OpenAIClient(client=NS(chat=NS(completions=comp)), sleep=lambda s: None))
    run = _wait(client, client.post(f"/projects/{pid}/plan/approve", json={}).json()["id"])
    assert run["status"] == "FAILED" and "per-run cost" in run["error"] and "LLM_MAX_COST_PER_RUN_USD" in run["error"]
    assert len(comp.create_calls) == 1  # nothing sent after the cap
    with Session(engine) as s:
        assert len(s.exec(select(LLMCall).where(LLMCall.run_id == run["id"])).all()) == 1


def test_request_time_budget_returns_402(client: TestClient, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "llm_daily_budget_usd", 0.0)
    comp = MockCompletions()
    set_llm(OpenAIClient(client=NS(chat=NS(completions=comp)), sleep=lambda s: None))
    r = client.post("/projects", json={"requirement": "Show revenue by month"})
    assert r.status_code == 402 and "daily budget" in r.json()["detail"]
    assert comp.parse_calls == []
    usage = client.get("/usage").json()
    assert usage["limits"]["daily_budget_usd"] == 0.0 and "cost_usd" in usage["today"]


def test_fix_loop_bound(client: TestClient, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "max_fix_attempts", 3)
    pid = _to_plan(client)
    fake = get_llm()
    fake.register("coder", "def run(input_dir, output_dir, params):\n    raise ValueError('boom')\n")
    run = _wait(client, client.post(f"/projects/{pid}/plan/approve", json={}).json()["id"])
    assert run["status"] == "FAILED" and "after 3 attempts" in run["error"]
    assert _agent_calls(fake, "coder") == 3
    assert _agent_calls(fake, "sanity") == 0 and _agent_calls(fake, "composer") == 0


def test_sanity_and_dashboard_qa_bounds(client: TestClient, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(settings, "max_sanity_rounds", 2)
    monkeypatch.setattr(settings, "max_dashboard_qa_rounds", 2)
    monkeypatch.setattr(settings, "screenshots_enabled", True)
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    monkeypatch.setattr(orch.screenshot, "capture", lambda run_id, out: ([shot] * 6, []))
    pid = _to_plan(client)
    fake = get_llm()
    fake.register("sanity", SanityReport(status="fail", issues=[
        SanityIssue(severity="high", check="implausible", message="always wrong")]))
    fake.register("dashboard_qa", {"issues": [DashboardIssue(severity="high", rule="vision", message="ugly")]})
    run = _wait(client, client.post(f"/projects/{pid}/plan/approve", json={}).json()["id"])
    assert run["status"] == "COMPLETED", run["error"]
    assert _agent_calls(fake, "coder") == 3  # 1 generation + 2 sanity fix rounds (code runs each time)
    assert _agent_calls(fake, "sanity") == 3 and _agent_calls(fake, "coder_spot_check") == 1
    assert _agent_calls(fake, "composer") == 3  # initial + 2 QA fix rounds
    qa_calls = [x for x in fake.calls if x["agent"] == "dashboard_qa"]
    assert len(qa_calls) == 3 and all(x["images"] == settings.llm_max_images for x in qa_calls)
    assert _agent_calls(fake, "insights") == 1 and run["dashboard_qa_json"]["rounds"] == 3


def test_duplicate_approve_409(client: TestClient, monkeypatch):  # noqa: F811
    monkeypatch.setattr(orch, "execute_first_run", lambda run_id: None)  # run stays QUEUED
    pid = _to_plan(client)
    first = client.post(f"/projects/{pid}/plan/approve", json={})
    assert first.status_code == 200
    second = client.post(f"/projects/{pid}/plan/approve", json={})
    assert second.status_code == 409 and "still queued" in second.json()["detail"]
    with Session(engine) as s:
        assert len(s.exec(select(Run).where(Run.project_id == pid)).all()) == 1
    with project_lock(pid, "plan generation"):  # concurrent plan request for the same project
        r = client.post(f"/projects/{pid}/plan")
        assert r.status_code == 409 and "busy" in r.json()["detail"]
    with Session(engine) as s:  # leave no active run behind for other tests
        run = s.get(Run, first.json()["id"])
        run.status = RunStatus.FAILED
        s.add(run)
        s.commit()


def test_startup_fails_interrupted_runs():
    from app.main import app

    with Session(engine) as s:
        p = Project(name="stuck", requirement_text="x", status="RUNNING")
        s.add(p)
        s.commit()
        s.refresh(p)
        runs = [Run(project_id=p.id, mode="script", status=st) for st in ("QUEUED", "RUNNING", "CHECKING")]
        done = Run(project_id=p.id, mode="script", status="COMPLETED")
        s.add_all([*runs, done])
        s.commit()
        ids = [r.id for r in runs]
        done_id, pid = done.id, p.id
    with TestClient(app):
        pass
    with Session(engine) as s:
        for i in ids:
            r = s.get(Run, i)
            assert r.status == "FAILED" and r.error == orch.INTERRUPTED
        assert s.get(Run, done_id).status == "COMPLETED"
        assert s.get(Project, pid).status == "FAILED"
