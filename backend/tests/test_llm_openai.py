"""OpenAIClient against a mocked SDK object (no network)."""
import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine, select

from app.llm import openai_client as oc
from app.llm.openai_client import LLMError, OpenAIClient, estimate_cost
from app.models.tables import LLMCall


class Answer(BaseModel):
    value: int


def _usage():
    return NS(prompt_tokens=100, completion_tokens=20)


def _parsed(obj):
    return NS(choices=[NS(message=NS(parsed=obj, refusal=None, content=None, tool_calls=None))], usage=_usage())


class MockCompletions:
    def __init__(self, parse_results=(), create_results=()):
        self.parse_results, self.create_results = list(parse_results), list(create_results)
        self.parse_calls, self.create_calls = [], []

    def _pop(self, queue):
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def parse(self, **kw):
        self.parse_calls.append(kw)
        return self._pop(self.parse_results)

    def create(self, **kw):
        self.create_calls.append(kw)
        return self._pop(self.create_results)


def make_client(comp: MockCompletions) -> OpenAIClient:
    return OpenAIClient(client=NS(chat=NS(completions=comp)), sleep=lambda s: None)


@pytest.fixture(autouse=True)
def no_db_log(monkeypatch):
    logged = []
    monkeypatch.setattr(OpenAIClient, "_log", staticmethod(lambda *a: logged.append(a)))
    return logged


def test_structured_with_images(no_db_log):
    comp = MockCompletions(parse_results=[_parsed(Answer(value=7))])
    out = make_client(comp).structured(agent="t", system="sys", user="hello", schema=Answer, images=[b"\x89PNG"],
                                       model="gpt-4.1-mini", project_id=3)
    assert out.value == 7
    kw = comp.parse_calls[0]
    rf = kw["response_format"]
    assert rf["json_schema"]["name"] == "Answer" and rf["json_schema"]["strict"] and kw["model"] == "gpt-4.1-mini"
    content = kw["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "hello"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert no_db_log[0][0] == "t" and no_db_log[0][4] == 3


def test_structured_refusal_raises():
    resp = NS(choices=[NS(message=NS(parsed=None, refusal="no"))], usage=_usage())
    with pytest.raises(LLMError):
        make_client(MockCompletions(parse_results=[resp])).structured(agent="t", system="", user="", schema=Answer)


def test_retries_transient_then_succeeds():
    err = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
    comp = MockCompletions(parse_results=[err, err, _parsed(Answer(value=1))])
    assert make_client(comp).structured(agent="t", system="", user="", schema=Answer).value == 1
    assert len(comp.parse_calls) == 3


def test_retries_give_up_after_three():
    err = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
    comp = MockCompletions(parse_results=[err, err, err, _parsed(Answer(value=1))])
    with pytest.raises(openai.APITimeoutError):
        make_client(comp).structured(agent="t", system="", user="", schema=Answer)


def test_text():
    comp = MockCompletions(create_results=[NS(choices=[NS(message=NS(content="hi"))], usage=_usage())])
    assert make_client(comp).text(agent="t", system="", user="") == "hi"


def test_tool_loop_runs_tools_and_reports_errors():
    def call(cid, name, args):
        return NS(id=cid, function=NS(name=name, arguments=json.dumps(args)))

    step1 = NS(choices=[NS(message=NS(content=None, tool_calls=[call("1", "add", {"a": 2, "b": 3}),
                                                                call("2", "boom", {})]))], usage=_usage())
    step2 = NS(choices=[NS(message=NS(content="done", tool_calls=None))], usage=_usage())
    comp = MockCompletions(create_results=[step1, step2], parse_results=[_parsed(Answer(value=5))])

    def boom():
        raise RuntimeError("bad")

    tools = {"add": ({"type": "object", "properties": {"a": {}, "b": {}}}, lambda a, b: a + b),
             "boom": ({"type": "object", "properties": {}}, boom)}
    out = make_client(comp).tool_loop(agent="v", system="", user="", tools=tools, schema=Answer)
    assert out.value == 5
    final_msgs = comp.parse_calls[0]["messages"]
    tool_msgs = [m for m in final_msgs if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "5" and "RuntimeError: bad" in tool_msgs[1]["content"]
    assert comp.create_calls[0]["tools"][0]["function"]["name"] == "add"


def test_tool_loop_caps_steps():
    looping = NS(choices=[NS(message=NS(content=None, tool_calls=[
        NS(id="1", function=NS(name="noop", arguments="{}"))]))], usage=_usage())
    comp = MockCompletions(create_results=[looping] * 5, parse_results=[_parsed(Answer(value=0))])
    make_client(comp).tool_loop(agent="v", system="", user="", schema=Answer, max_steps=2,
                                tools={"noop": ({"type": "object", "properties": {}}, lambda: "ok")})
    assert len(comp.create_calls) == 2 and len(comp.parse_calls) == 1


def test_log_writes_row_and_never_raises(monkeypatch):
    monkeypatch.undo()  # restore the real _log
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    import app.core.db as db

    monkeypatch.setattr(db, "engine", eng)
    OpenAIClient._log("analyst", "gpt-4.1", NS(usage=_usage()), 0.5, 1)
    with Session(eng) as s:
        row = s.exec(select(LLMCall)).one()
    assert row.prompt_tokens == 100 and row.cost == pytest.approx(estimate_cost("gpt-4.1", 100, 20))
    monkeypatch.setattr(db, "engine", None)
    OpenAIClient._log("analyst", "gpt-4.1", object(), 0.1, None)  # broken DB: swallowed


def test_estimate_cost_prefix():
    assert estimate_cost("gpt-4.1-mini-2025-04-14", 1_000_000, 0) == pytest.approx(0.40)
    assert estimate_cost("unknown-model", 1_000_000, 0) == pytest.approx(5.00)  # fail safe, not free
    assert oc.PRICES["gpt-4.1"][0] > oc.PRICES["gpt-4.1-mini"][0]
