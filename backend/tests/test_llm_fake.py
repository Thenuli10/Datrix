import inspect

import pytest
from pydantic import BaseModel

import app.schemas as schemas
from app.core.config import settings
from app.llm import get_llm, set_llm
from app.llm.fake import FakeLLMClient, minimal_instance
from app.schemas import AnalysisPlan, DashboardSpec, Layout, RequirementAnalysis

ALL_SCHEMAS = [obj for _, obj in inspect.getmembers(schemas, inspect.isclass) if issubclass(obj, BaseModel)]


@pytest.mark.parametrize("schema", ALL_SCHEMAS, ids=lambda s: s.__name__)
def test_minimal_instance_for_every_schema(schema):
    assert isinstance(minimal_instance(schema), schema)


def test_minimal_instance_respects_constraints():
    lay = minimal_instance(Layout)
    assert lay.w >= 1 and lay.h >= 1
    ra = minimal_instance(RequirementAnalysis)
    assert ra.task_type == "prediction" and ra.data_spec.columns == []


def test_register_instance_dict_str_callable_and_queue():
    fake = FakeLLMClient()
    plan = minimal_instance(AnalysisPlan)
    fake.register("planner", plan)
    assert fake.structured(agent="planner", system="s", user="u", schema=AnalysisPlan) is plan
    fake.register("composer", [{"title": "A", "widgets": []}, '{"title": "B", "widgets": []}'])
    assert fake.structured(agent="composer", system="", user="", schema=DashboardSpec).title == "A"
    assert fake.structured(agent="composer", system="", user="", schema=DashboardSpec).title == "B"
    assert fake.structured(agent="composer", system="", user="", schema=DashboardSpec).title == "B"  # last sticks
    fake.register("x", lambda system, user, schema: schema(title=user, widgets=[]))
    assert fake.structured(agent="x", system="", user="hi", schema=DashboardSpec).title == "hi"
    assert [c["agent"] for c in fake.calls] == ["planner", "composer", "composer", "composer", "x"]


def test_text_defaults_and_tool_loop_callable():
    fake = FakeLLMClient()
    assert "def run(" in fake.text(agent="coder", system="", user="")
    assert fake.text(agent="other", system="", user="") == ""

    def fn(system, user, schema, tools):
        return schema(title=str(tools["add"][1](a=1, b=2)), widgets=[])

    fake.register("v", fn)
    out = fake.tool_loop(agent="v", system="", user="", tools={"add": ({}, lambda a, b: a + b)}, schema=DashboardSpec)
    assert out.title == "3"
    assert fake.calls[-1]["tools"] == ["add"]


def test_get_llm_fake_when_no_key(monkeypatch):
    set_llm(None)
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert isinstance(get_llm(), FakeLLMClient)
    assert get_llm() is get_llm()
    custom = FakeLLMClient()
    set_llm(custom)
    assert get_llm() is custom
    set_llm(None)
